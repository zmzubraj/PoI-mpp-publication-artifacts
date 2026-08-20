import argparse, csv, random
p=argparse.ArgumentParser(); p.add_argument('--trials',type=int,default=10000); p.add_argument('--k',type=int,default=8); p.add_argument('--out',default='../results/raw/e4_da.csv'); a=p.parse_args()
r=random.Random(4)
with open(a.out,'w',newline='') as f:
    w=csv.writer(f); w.writerow(['withheld_fraction','k','empirical_miss','theoretical_miss'])
    for frac in [0.05,0.10,0.20,0.30,0.50]:
        miss=0
        for _ in range(a.trials):
            if all(r.random()>=frac for __ in range(a.k)): miss+=1
        w.writerow([frac,a.k,miss/a.trials,(1-frac)**a.k])
