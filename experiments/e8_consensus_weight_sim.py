import argparse, csv, random
p=argparse.ArgumentParser(); p.add_argument('--out',default='../results/raw/e8_consensus.csv'); a=p.parse_args()
r=random.Random(8)
workers=[f'w{i}' for i in range(10)]
q={w:r.randint(20,100) for w in workers}; b={w:r.randint(200,1200) for w in workers}; beta=10
weights={w:min(q[w],b[w]//beta) for w in workers}
t=sum(weights.values())
with open(a.out,'w',newline='') as f:
    wr=csv.writer(f); wr.writerow(['worker','Q','bond','W','prob']);
    for w in workers: wr.writerow([w,q[w],b[w],weights[w],weights[w]/t])
print('total_weight',t,'max_share',max(weights.values())/t)
