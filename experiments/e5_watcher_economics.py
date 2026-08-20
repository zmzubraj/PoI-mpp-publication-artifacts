import argparse, csv, math
p=argparse.ArgumentParser(); p.add_argument('--out',default='../results/raw/e5_watcher.csv'); a=p.parse_args()
with open(a.out,'w',newline='') as f:
    w=csv.writer(f); w.writerow(['watchers','p_individual','p_no_challenge','expected_detect'])
    for n in [1,2,4,8,16,32]:
        for p_i in [0.1,0.25,0.5,0.75]:
            p_none=(1-p_i)**n
            w.writerow([n,p_i,p_none,1-p_none])
