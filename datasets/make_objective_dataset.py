import json, random, argparse
p=argparse.ArgumentParser(); p.add_argument('--n',type=int,default=2000); p.add_argument('--out',default='generated/objective.jsonl'); a=p.parse_args()
r=random.Random(42)
with open(a.out,'w') as f:
    for i in range(a.n):
        x,y=r.randint(10,999),r.randint(10,999)
        rec={"id":f"obj-{i}","task":"arithmetic","prompt":f"Compute {x} + {y}. Return only the integer.","answer":str(x+y)}
        f.write(json.dumps(rec)+'\n')
print(a.out)
