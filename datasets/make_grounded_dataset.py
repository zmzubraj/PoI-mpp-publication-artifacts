import json, random, argparse
p=argparse.ArgumentParser(); p.add_argument('--n',type=int,default=500); p.add_argument('--out',default='generated/grounded.jsonl'); a=p.parse_args()
r=random.Random(7)
entities=[("Aster", "Rivermark", "2018"),("Beryl", "Stonehaven", "2021"),("Cobalt", "Lakewood", "2016"),("Delta", "Northbridge", "2023")]
with open(a.out,'w') as f:
    for i in range(a.n):
        name,city,year=r.choice(entities)
        evidence=f"Project {name} was launched in {year} and its reference office is in {city}."
        q=f"According to the evidence, where is Project {name}'s reference office?"
        rec={"id":f"g-{i}","task":"grounded_qa","question":q,"evidence":[{"id":"e1","text":evidence,"keywords":[name,city,year]}],"answer_terms":[city]}
        f.write(json.dumps(rec)+'\n')
print(a.out)
