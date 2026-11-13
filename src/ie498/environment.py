from dataclasses import asdict, dataclass
import numpy as np
from scipy.optimize import minimize, minimize_scalar, root
from scipy.special import softmax


@dataclass(frozen=True)
class Market:
    a: tuple = (2.0, 2.0)
    c: tuple = (1.0, 1.0)
    a0: float = 0.0
    mu: float = 0.25
    alpha: float = 1.0
    beta: float = 100.0

    def settle(self, prices):
        p = np.asarray(prices, dtype=float)
        if p.shape != (len(self.a),) or not np.all(np.isfinite(p)) or np.any(p < 0):
            raise ValueError("Prices must be finite, nonnegative, and match firms")
        logits = np.r_[self.a0 / self.mu, (np.array(self.a) - p / self.alpha) / self.mu]
        q = self.beta * softmax(logits)[1:]
        profit = (p - self.alpha * np.asarray(self.c)) * q
        return q, profit

    def benchmarks(self):
        def foc(p):
            q, _ = self.settle(p)
            return 1 - (p - self.alpha * np.array(self.c)) / (self.alpha * self.mu) * (1 - q / self.beta)
        nash = root(foc, np.array(self.c) * self.alpha + 0.5 * self.alpha)
        if not nash.success or np.max(np.abs(foc(nash.x))) > 1e-8:
            raise RuntimeError("Nash solve failed")
        joint = minimize(lambda p: -sum(self.settle(p)[1]), np.full(len(self.a), 1.9 * self.alpha),
                         bounds=[(0, None)] * len(self.a), method="L-BFGS-B", options={"ftol": 1e-14, "gtol": 1e-9})
        if not joint.success:
            raise RuntimeError("Joint solve failed")
        best_responses = []
        for i in range(len(self.a)):
            def objective(x):
                p = nash.x.copy(); p[i] = x
                return -self.settle(p)[1][i]
            best_responses.append(minimize_scalar(objective, bounds=(0, 10 * self.alpha), method="bounded").x)
        return {"parameters": asdict(self), "nash_price": nash.x.tolist(),
                "nash_profit": self.settle(nash.x)[1].tolist(), "best_response_check": best_responses,
                "joint_price": joint.x.tolist(), "joint_profit": self.settle(joint.x)[1].tolist()}
