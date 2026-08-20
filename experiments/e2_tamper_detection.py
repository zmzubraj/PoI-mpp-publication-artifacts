import argparse, csv, random, math
p=argparse.ArgumentParser(); p.add_argument('--trials',type=int,default=5000); p.add_argument('--out',default='../results/raw/e2_tamper.csv'); a=p.parse_args()
r=random.Random(2)
settings=[0.01,0.02,0.05,0.10]
with open(a.out,'w',newline='') as f:
    w=csv.writer(f); w.writerow(['sample_fraction','trials','detected','rate'])
    for s in settings:
        det=0
        for _ in range(a.trials):
            corrupted_fraction=r.choice([0.01,0.02,0.05,0.10])
            # probability at least one corrupted region is sampled in a simple independent model
            k=max(1,int(round(100*s)))
            pdet=1-(1-corrupted_fraction)**k
            det += (r.random()<pdet)
        w.writerow([s,a.trials,det,det/a.trials])
