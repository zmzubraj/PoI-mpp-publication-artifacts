import argparse, csv, random
p=argparse.ArgumentParser(); p.add_argument('--n',type=int,default=1000); p.add_argument('--out',default='../results/raw/e3_semantic.csv'); a=p.parse_args()
r=random.Random(3)
# Synthetic verifier-calibration harness; replace with real model/evidence verifier outputs.
labels=[]
for i in range(a.n):
    truth=1 if r.random()<0.7 else 0
    score=min(1,max(0,r.gauss(0.86 if truth else 0.35,0.12)))
    disagree=min(1,max(0,r.gauss(0.10 if truth else 0.18,0.08)))
    decision='ABSTAIN' if disagree>0.25 else ('ACCEPT' if score>=0.8 else 'REJECT')
    labels.append((truth,score,disagree,decision))
fa=sum(1 for t,s,d,x in labels if t==0 and x=='ACCEPT')
fr=sum(1 for t,s,d,x in labels if t==1 and x=='REJECT')
ab=sum(1 for *_,x in labels if x=='ABSTAIN')
with open(a.out,'w',newline='') as f:
    w=csv.writer(f); w.writerow(['truth','score','disagreement','decision']); w.writerows(labels)
print({'FAR':fa/max(1,sum(1 for t,*_ in labels if t==0)),'FRR':fr/max(1,sum(1 for t,*_ in labels if t==1)),'ABSTAIN':ab/a.n})
