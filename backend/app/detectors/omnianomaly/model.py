"""OmniAnomaly (Su et al., KDD 2019) — PyTorch port of the load-bearing mechanisms.

Faithful to https://github.com/NetManAIOps/OmniAnomaly. Implemented mechanisms:

  * GRU encoder (qnet) and GRU decoder (pnet) over a length-T window.
  * A stochastic latent z_t at every timestep (VAE).
  * Planar normalizing-flow posterior q(z_t | x) — `PlanarFlow` stack.
  * A linear-Gaussian transition prior p(z_t | z_{t-1}) = N(A z_{t-1}, I) — the
    "stochastic recurrence" that connects latents over time.
  * ELBO objective including the flow log-determinant (change of variables).
  * Anomaly score = negative reconstruction probability of the window's LAST
    point, Monte-Carlo averaged over posterior samples; per-dimension version
    drives root-cause interpretation.

Documented deviations from the original (mle-practices §1):
  * The prior is a first-order learnable linear-Gaussian transition, not
    zhusuan's full LinearGaussianStateSpaceModel (Kalman). This preserves the
    stochastic-recurrence mechanism; it simplifies the exact transition/covariance.
  * Gaussian observation likelihood; no missing-data MCMC imputation (we assume
    complete windows).
  * Single posterior sample during training; L samples only for scoring.
"""

from __future__ import annotations

import math

import torch
from torch import nn
from torch.nn import functional as F

_LOG_2PI = math.log(2.0 * math.pi)


def _gauss_logprob(x: torch.Tensor, mu: torch.Tensor, logvar: torch.Tensor) -> torch.Tensor:
    """Diagonal-Gaussian log-density, summed over the last (feature) dim."""
    return (-0.5 * (_LOG_2PI + logvar + (x - mu) ** 2 / torch.exp(logvar))).sum(-1)


class PlanarFlow(nn.Module):
    """A single planar flow f(z) = z + u_hat * tanh(w·z + b), with the
    invertibility reparameterization of u (Rezende & Mohamed, 2015)."""

    def __init__(self, dim: int) -> None:
        super().__init__()
        self.u = nn.Parameter(torch.randn(dim) * 0.01)
        self.w = nn.Parameter(torch.randn(dim) * 0.01)
        self.b = nn.Parameter(torch.zeros(1))

    def forward(self, z: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        wu = (self.w * self.u).sum()
        m = -1.0 + F.softplus(wu)
        u_hat = self.u + (m - wu) * self.w / (self.w * self.w).sum()
        lin = (z * self.w).sum(-1, keepdim=True) + self.b          # (..., 1)
        f = z + u_hat * torch.tanh(lin)
        psi = (1.0 - torch.tanh(lin) ** 2) * self.w                 # (..., dim)
        log_det = torch.log(torch.abs(1.0 + (psi * u_hat).sum(-1)) + 1e-8)  # (...)
        return f, log_det


class OmniAnomaly(nn.Module):
    def __init__(
        self,
        n_features: int,
        z_dim: int = 3,
        hidden: int = 32,
        n_flows: int = 2,
    ) -> None:
        super().__init__()
        self.z_dim = z_dim
        # qnet (inference): GRU over inputs -> posterior params -> planar flows
        self.enc_gru = nn.GRU(n_features, hidden, batch_first=True)
        self.z_mu = nn.Linear(hidden, z_dim)
        self.z_logvar = nn.Linear(hidden, z_dim)
        self.flows = nn.ModuleList(PlanarFlow(z_dim) for _ in range(n_flows))
        # linear-Gaussian transition prior p(z_t | z_{t-1})
        self.transition = nn.Linear(z_dim, z_dim, bias=False)
        # pnet (generative): GRU over z -> observation params
        self.dec_gru = nn.GRU(z_dim, hidden, batch_first=True)
        self.x_mu = nn.Linear(hidden, n_features)
        self.x_logvar = nn.Linear(hidden, n_features)

    def _forward_once(self, x: torch.Tensor):
        b, t, _ = x.shape
        h_enc, _ = self.enc_gru(x)
        z_mu = self.z_mu(h_enc)
        z_logvar = self.z_logvar(h_enc).clamp(-6.0, 6.0)
        z0 = z_mu + torch.exp(0.5 * z_logvar) * torch.randn_like(z_mu)

        log_q0 = _gauss_logprob(z0, z_mu, z_logvar)                 # (B, T)
        z = z0
        flow_ld = torch.zeros(b, t, device=x.device)
        for flow in self.flows:
            z, ld = flow(z)
            flow_ld = flow_ld + ld
        log_qz = log_q0 - flow_ld                                  # change of variables

        z_prev = torch.cat([torch.zeros(b, 1, self.z_dim, device=x.device), z[:, :-1, :]], dim=1)
        prior_mu = self.transition(z_prev)
        log_pz = _gauss_logprob(z, prior_mu, torch.zeros_like(z))   # N(A z_{t-1}, I)

        h_dec, _ = self.dec_gru(z)
        x_mu = self.x_mu(h_dec)
        x_logvar = self.x_logvar(h_dec).clamp(-6.0, 6.0)
        return log_qz, log_pz, x_mu, x_logvar

    def elbo_loss(self, x: torch.Tensor) -> torch.Tensor:
        log_qz, log_pz, x_mu, x_logvar = self._forward_once(x)
        log_px = _gauss_logprob(x, x_mu, x_logvar)                 # (B, T)
        elbo = (log_px + log_pz - log_qz).mean()
        return -elbo

    @torch.no_grad()
    def score_last(self, x: torch.Tensor, n_samples: int) -> tuple[torch.Tensor, torch.Tensor]:
        """Reconstruction log-prob of the window's last point, MC-averaged.
        Returns ``(aggregate (B,), per_dim (B, D))``."""
        b, _, d = x.shape
        agg = torch.zeros(b, device=x.device)
        per_dim = torch.zeros(b, d, device=x.device)
        for _ in range(n_samples):
            _, _, x_mu, x_logvar = self._forward_once(x)
            xt, mu_t, lv_t = x[:, -1, :], x_mu[:, -1, :], x_logvar[:, -1, :]
            ll_dim = -0.5 * (_LOG_2PI + lv_t + (xt - mu_t) ** 2 / torch.exp(lv_t))  # (B, D)
            per_dim += ll_dim
            agg += ll_dim.sum(-1)
        return agg / n_samples, per_dim / n_samples
