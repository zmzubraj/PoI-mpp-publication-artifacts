import argparse, csv, random
p=argparse.ArgumentParser(); p.add_argument('--tasks',type=int,default=10000); p.add_argument('--out',default='../results/raw/e6_sybil.csv'); a=p.parse_args()
r=random.Random(6)
with open(a.out,'w',newline='') as f:
    w=csv.writer(f); w.writerow(['sybil_identities','scheduler','expected_credit_share'])
    for n in [1,2,4,8,16,32]:
        # unsafe identity-uniform scheduler
        w.writerow([n,'identity_uniform',n/(n+9)])
        # operator/capacity-neutral scheduler: identity split should not alter share
        w.writerow([n,'capacity_neutral',1/10])
