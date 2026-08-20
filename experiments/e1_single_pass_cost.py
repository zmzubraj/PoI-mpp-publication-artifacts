import argparse, csv, random, statistics
p=argparse.ArgumentParser(); p.add_argument('--n',type=int,default=200); p.add_argument('--out',default='../results/raw/e1_cost.csv'); a=p.parse_args()
r=random.Random(1)
rows=[]
for i in range(a.n):
    infer=r.gauss(1.0,0.05); trace=max(0,r.gauss(0.12,0.02)); audit=max(0,r.gauss(0.06,0.02)); dispute=0.5 if r.random()<0.02 else 0
    rows.append((i,infer,2*infer,infer+trace+audit+dispute))
with open(a.out,'w',newline='') as f:
    w=csv.writer(f); w.writerow(['i','single_run','two_run','spai']); w.writerows(rows)
print('mean_single',statistics.mean(x[1] for x in rows),'mean_two',statistics.mean(x[2] for x in rows),'mean_spai',statistics.mean(x[3] for x in rows))
