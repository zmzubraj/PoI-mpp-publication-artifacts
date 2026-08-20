import numpy as np
from auditor.freivalds import verify_matmul

def test_honest():
    A=np.array([[1.,2.],[3.,4.]])
    B=np.array([[5.,6.],[7.,8.]])
    C=A@B
    assert verify_matmul(A,B,C,rounds=8,seed=1)

def test_tampered():
    A=np.array([[1.,2.],[3.,4.]])
    B=np.array([[5.,6.],[7.,8.]])
    C=A@B; C[0,0]+=1
    assert not verify_matmul(A,B,C,rounds=8,seed=1)
