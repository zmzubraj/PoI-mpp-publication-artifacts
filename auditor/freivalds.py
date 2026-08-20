import numpy as np

def verify_matmul(A, B, C, rounds=8, seed=0, atol=1e-5):
    """Verify C ~= A@B using randomized Freivalds checks. Floating-point research prototype."""
    rng=np.random.default_rng(seed)
    for _ in range(rounds):
        r=rng.integers(0,2,size=(B.shape[1],1)).astype(np.float64)
        lhs=C.astype(np.float64) @ r
        rhs=A.astype(np.float64) @ (B.astype(np.float64) @ r)
        if not np.allclose(lhs,rhs,atol=atol,rtol=atol):
            return False
    return True
