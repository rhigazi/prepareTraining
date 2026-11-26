#!/usr/bin/env python3
"""run_visual_opt_search.py - Optimize for strong segment hits with fewer extra signals."""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

import numpy as np
import talib
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN = os.path.join(HERE, "train_turning_points.py")
EXTREMES = os.path.join(HERE, "extremes_tool.py")
PY = sys.executable
RAW_DIR = os.path.join(HERE, "raw_data")
SEARCH_DIR = os.path.join(HERE, "runs", "visual_opt")

if HERE not in sys.path:
    sys.path.insert(0, HERE)
import extremes_tool as et
import ml4t_features as mf
import prepareTraining as pt

# reuse ml4t make_prepared logic by importing? We'll implement local using ml4t_features
import pandas as pd


def make_prepared(tol, dst):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    os.makedirs(dst, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(RAW_DIR, "*.csv"))):
        df = pd.read_csv(path)
        for col in ["t", "o", "h", "l", "c", "v"]:
            if col not in df.columns:
                raise ValueError(f"Missing {col}")
        if "vw" not in df.columns:
            df["vw"] = df["c"]
        df = pt.sort_and_dedup(df)
        # compute ml4t features
        # temporarily attach c/h/l etc by using ml4t_features.compute_features on a copy with original cols
        # ml4t_features expects df with t,o,h,l,c,v,vw
        work = df.copy()
        work = mf.compute_features(work)
        # labels from SMA segments
        c = df["c"].to_numpy(float); h = df["h"].to_numpy(float); l = df["l"].to_numpy(float)
        # sma segment labels
        s38 = pd.Series(c).rolling(38, min_periods=38).mean().to_numpy()
        s80 = pd.Series(c).rolling(80, min_periods=80).mean().to_numpy()
        diff = s38 - s80
        crosses = [0]
        for i in range(1, len(c)):
            if not (np.isfinite(diff[i-1]) and np.isfinite(diff[i])): continue
            if diff[i-1] == 0: continue
            if np.sign(diff[i]) != np.sign(diff[i-1]) and diff[i] != 0:
                crosses.append(i)
        crosses.append(len(c)-1); crosses = sorted(set(crosses))
        labels = np.zeros(len(c))
        for a,b in zip(crosses, crosses[1:]):
            if b-a < 1: continue
            mid=(a+b)//2
            if not np.isfinite(diff[mid]): continue
            if diff[mid] > 0:
                pos=int(np.nanargmax(h[a:b+1])+a); labels[pos]=-1.0
            else:
                pos=int(np.nanargmin(l[a:b+1])+a); labels[pos]=1.0
        # expand tolerance
        if tol > 0:
            outl = labels.copy()
            n=len(labels)
            for i in range(n):
                if labels[i]!=0:
                    for j in range(max(0,i-tol), min(n,i+tol+1)):
                        if outl[j]==0: outl[j]=labels[i]
            labels=outl
        # ATR label_max_move
        atr = talib.ATR(h,l,c,timeperiod=14)
        wr=6
        fut_min_low = pd.Series(l).rolling(window=wr,min_periods=wr).min().shift(-wr).to_numpy()
        fut_max_high = pd.Series(h).rolling(window=wr,min_periods=wr).max().shift(-wr).to_numpy()
        valid_future = np.isfinite(fut_min_low)&np.isfinite(fut_max_high)
        drop=h-fut_min_low; rise=fut_max_high-l
        up_move=(fut_max_high-l)/atr; down_move=(h-fut_min_low)/atr
        label_max_move=np.maximum(up_move,down_move)
        hm=labels==-1; lm=labels==1
        label_max_move[hm]=(drop/atr)[hm]; label_max_move[lm]=(rise/atr)[lm]
        incomplete=~valid_future
        labels[incomplete]=np.nan; label_max_move[incomplete]=np.nan

        work["label_turn"]=labels
        work["label_max_move_atr"]=label_max_move
        # meta columns already from df? work from mf.compute_features uses pt.sort_and_dedup, keeps original cols
        # ensure meta columns
        if "meta_t" not in work.columns:
            work.insert(0,"meta_t", df["t"].values)
        if "meta_ticker" not in work.columns:
            work.insert(1,"meta_ticker", pt.parse_ticker_timeframe(path)[0])
        if "meta_timeframe" not in work.columns:
            work.insert(2,"meta_timeframe", pt.parse_ticker_timeframe(path)[1])
        if "meta_open" not in work.columns:
            work["meta_open"]=df["o"].values
            work["meta_high"]=df["h"].values
            work["meta_low"]=df["l"].values
            work["meta_close"]=df["c"].values

        feat_cols=[col for col in work.columns if col.startswith("feat_")]
        work=work.replace([np.inf,-np.inf],np.nan)
        work=work.dropna(subset=feat_cols+["label_turn","label_max_move_atr"]).reset_index(drop=True)
        work["label_turn"]=work["label_turn"].astype(int)
        if work.empty: continue
        stem=os.path.splitext(os.path.basename(path))[0]
        work.to_csv(os.path.join(dst, f"{stem}_prepared.csv"), index=False)
    return dst


def run_train(trial_name, data_dir, extra_args, epochs):
    out_dir=os.path.join(SEARCH_DIR,trial_name)
    if os.path.exists(out_dir): shutil.rmtree(out_dir)
    cmd=[PY,TRAIN,"--input-dir",data_dir,"--output-dir",out_dir,"--out-of-tickers","AAPL","--epochs",str(epochs)]+extra_args
    print(f"\n=== {trial_name} ===")
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)
    log_path=os.path.join(out_dir,"training_run.log")
    val_f1=None; overall=[]
    with open(log_path) as f:
        for line in f:
            m=re.search(r"Val Turn \(filtered\) P/R/F1: [\d.]+/[\d.]+/([\d.]+)",line)
            if m: val_f1=float(m.group(1))
            m2=re.search(r"Overall Turn Precision/Recall/F1: ([\d.]+)/([\d.]+)/([\d.]+)",line)
            if m2: overall.append(float(m2.group(3)))
    oot_f1=overall[-1] if len(overall)>=2 else (overall[0] if overall else None)
    return out_dir,val_f1,oot_f1


def validate_trial(model_dir):
    ckpt,scaler,model,threshold,cooldown=et.load_model(model_dir)
    hits_b=misses_b=hits_r=misses_r=0; te=ts=0
    for path in sorted(glob.glob(os.path.join(RAW_DIR,"*.csv"))):
        raw=pd.read_csv(path)
        ann,probs,ft,valid=et.annotate_df(raw,ckpt,scaler,model,threshold,cooldown)
        close,high,low,t=et.standardize_ohlc(ann)
        s38,s80,segs,crosses=et.sma_cross_segments(close,high,low)
        h,m,extra,eb,er,matched=et.validate_segments(ft,segs,tolerance=5)
        hits_b+=h["bull"]; misses_b+=m["bull"]; hits_r+=h["bear"]; misses_r+=m["bear"]; te+=len(extra); ts+=int((ft!=0).sum())
    hr_b=hits_b/(hits_b+misses_b) if (hits_b+misses_b) else 0.0
    hr_r=hits_r/(hits_r+misses_r) if (hits_r+misses_r) else 0.0
    return {"hits_bull":hits_b,"misses_bull":misses_b,"hit_rate_bull":hr_b,
            "hits_bear":hits_r,"misses_bear":misses_r,"hit_rate_bear":hr_r,
            "extra":te,"model_sigs":ts}


def composite_score(val_f1,oot_f1,v):
    val_f1=val_f1 or 0.0; oot_f1=oot_f1 or 0.0
    hr_avg=(v["hit_rate_bull"]+v["hit_rate_bear"])/2.0
    extra_rate=(v["extra"]/v["model_sigs"]) if v["model_sigs"]>0 else 1.0
    extra_rate=min(extra_rate,1.0)
    penalty=0.0
    if v["model_sigs"]<100: penalty+=(100-v["model_sigs"])/100.0
    if v["model_sigs"]>2000: penalty+=(v["model_sigs"]-2000)/2000.0
    score=0.30*val_f1+0.20*oot_f1+0.35*hr_avg+0.15*(1-extra_rate)-0.10*penalty
    return max(0.0,min(1.0,score))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--epochs",type=int,default=12)
    parser.add_argument("--trials",type=int,default=12)
    args=parser.parse_args()

    os.makedirs(SEARCH_DIR,exist_ok=True)
    # prepared datasets
    print("Preparing datasets...")
    data_tol0=make_prepared(0, os.path.join(SEARCH_DIR,"prepared_tol0"))
    data_tol1=make_prepared(1, os.path.join(SEARCH_DIR,"prepared_tol1"))
    data_tol2=make_prepared(2, os.path.join(SEARCH_DIR,"prepared_tol2"))

    configs=[
        ("vis_01", data_tol0, ["--hidden-dims","64","32","--dropout","0.35","--class-weight-power","0.5","--learning-rate","5e-4","--cooldown-bars","8","--threshold-min","0.50","--threshold-max","0.60"]),
        ("vis_02", data_tol1, ["--hidden-dims","64","32","--dropout","0.35","--class-weight-power","0.5","--learning-rate","5e-4","--cooldown-bars","8","--threshold-min","0.50","--threshold-max","0.60"]),
        ("vis_03", data_tol2, ["--hidden-dims","64","32","--dropout","0.35","--class-weight-power","0.5","--learning-rate","5e-4","--cooldown-bars","8","--threshold-min","0.50","--threshold-max","0.60"]),
        ("vis_04", data_tol1, ["--hidden-dims","96","48","--dropout","0.4","--class-weight-power","0.6","--learning-rate","7e-4","--cooldown-bars","10","--threshold-min","0.55","--threshold-max","0.65"]),
        ("vis_05", data_tol2, ["--hidden-dims","96","48","--dropout","0.4","--class-weight-power","0.6","--learning-rate","7e-4","--cooldown-bars","10","--threshold-min","0.55","--threshold-max","0.65"]),
        ("vis_06", data_tol0, ["--hidden-dims","64","32","--dropout","0.3","--class-weight-power","0.4","--learning-rate","5e-4","--cooldown-bars","12","--threshold-min","0.50","--threshold-max","0.60"]),
        ("vis_07", data_tol1, ["--hidden-dims","128","64","--dropout","0.45","--class-weight-power","0.7","--learning-rate","1e-3","--cooldown-bars","8","--threshold-min","0.45","--threshold-max","0.55"]),
        ("vis_08", data_tol2, ["--hidden-dims","128","64","--dropout","0.45","--class-weight-power","0.7","--learning-rate","1e-3","--cooldown-bars","8","--threshold-min","0.45","--threshold-max","0.55"]),
        ("vis_09", data_tol1, ["--hidden-dims","64","32","--dropout","0.35","--class-weight-power","0.5","--learning-rate","5e-4","--cooldown-bars","10","--threshold-min","0.60","--threshold-max","0.70"]),
        ("vis_10", data_tol0, ["--hidden-dims","64","32","--dropout","0.35","--class-weight-power","0.5","--learning-rate","5e-4","--cooldown-bars","10","--threshold-min","0.60","--threshold-max","0.70"]),
        ("vis_11", data_tol2, ["--hidden-dims","96","48","--dropout","0.4","--class-weight-power","0.6","--learning-rate","7e-4","--cooldown-bars","12","--threshold-min","0.55","--threshold-max","0.65"]),
        ("vis_12", data_tol1, ["--hidden-dims","64","32","--dropout","0.3","--class-weight-power","0.4","--learning-rate","5e-4","--cooldown-bars","6","--threshold-min","0.50","--threshold-max","0.60"]),
    ]
    configs=configs[:args.trials]

    rows=[]
    for name,data_dir,extra in configs:
        try:
            out_dir,val_f1,oot_f1=run_train(name,data_dir,extra,args.epochs)
            v=validate_trial(out_dir)
            score=composite_score(val_f1,oot_f1,v)
            tol=os.path.basename(data_dir).replace("prepared_tol","")
            row={"trial":name,"label_tol":tol,"data_dir":data_dir,"val_f1":val_f1,"oot_f1":oot_f1,
                 "hit_rate_bull":v["hit_rate_bull"],"hit_rate_bear":v["hit_rate_bear"],
                 "extra":v["extra"],"model_sigs":v["model_sigs"],"score":score,"params":" ".join(extra)}
            rows.append(row)
            print(f"{name}: val={val_f1} oot={oot_f1} hr_bull={v['hit_rate_bull']:.3f} hr_bear={v['hit_rate_bear']:.3f} sigs={v['model_sigs']} extra={v['extra']} score={score:.4f}")
        except Exception as e:
            print(f"Trial {name} failed: {e}", file=sys.stderr)

    summary_path=os.path.join(SEARCH_DIR,"experiments_log.csv")
    if rows:
        df=pd.DataFrame(rows).sort_values("score",ascending=False)
        df.to_csv(summary_path,index=False)
        best_name=df.iloc[0]["trial"]
        best_dir=os.path.join(SEARCH_DIR,best_name)
        best_target=os.path.join(SEARCH_DIR,"best")
        if os.path.exists(best_target): shutil.rmtree(best_target)
        shutil.copytree(best_dir,best_target)
        print("Best:",best_name,df.iloc[0]["score"])
        # validation + charts
        cmd=[PY,EXTREMES,"--mode","all","--input-dir",RAW_DIR,"--output-dir",best_target,"--model-dir",best_target,"--tolerance-bars","5","--window-bars","400"]
        subprocess.run(cmd,check=True)
        # report
        top=df.head(5)
        def load_summary(d):
            p=os.path.join(d,"reports","sma_validation_summary.csv")
            return pd.read_csv(p) if os.path.exists(p) else None
        opt01=load_summary(os.path.join(HERE,"extremes_output"))
        ml4t=load_summary(os.path.join(HERE,"runs","ml4t_search","best"))
        best_v=validate_trial(best_target)
        report_path=os.path.join(SEARCH_DIR,"visual_opt_report.md")
        with open(report_path,"w") as f:
            f.write("# Visual Opt Search – Ergebnisse\n\n")
            f.write("## Top-5 Experimente\n\n")
            f.write(top[["trial","label_tol","val_f1","oot_f1","hit_rate_bull","hit_rate_bear","model_sigs","extra","score"]].to_markdown(index=False))
            f.write("\n\n## Bester Lauf\n\n")
            f.write(f"- Trial: {best_name}\n- Score: {df.iloc[0]['score']:.4f}\n- Dir: {best_target}\n")
            f.write(f"- Validierung/Charts: {best_target}/charts/ (inkl. AAPL_1Hour Bars 1600–1999)\n\n")
            if opt01 is not None:
                o=opt01; o_tot=o["model_signals"].sum(); o_extra=o["extra_signals"].sum()
                o_hb=o["hits_bull"].sum(); o_mb=o["misses_bull"].sum()
                o_hr=o["hits_bear"].sum(); o_mr=o["misses_bear"].sum()
                f.write("## Vergleich vs. opt_01\n\n")
                f.write(f"- opt_01: Signale {o_tot}, Extra {o_extra}, Hit Bull {o_hb}/{o_hb+o_mb} ({o_hb/(o_hb+o_mb):.2f}), Hit Bear {o_hr}/{o_hr+o_mr} ({o_hr/(o_hr+o_mr):.2f})\n")
            if ml4t is not None:
                m=ml4t; m_tot=m["model_signals"].sum(); m_extra=m["extra_signals"].sum()
                m_hb=m["hits_bull"].sum(); m_mb=m["misses_bull"].sum()
                m_hr=m["hits_bear"].sum(); m_mr=m["misses_bear"].sum()
                f.write("## Vergleich vs. ml4t_07\n\n")
                f.write(f"- ml4t_07: Signale {m_tot}, Extra {m_extra}, Hit Bull {m_hb}/{m_hb+m_mb} ({m_hb/(m_hb+m_mb):.2f}), Hit Bear {m_hr}/{m_hr+m_mr} ({m_hr/(m_hr+m_mr):.2f})\n")
            f.write("## Bester visueller Kandidat\n\n")
            f.write(f"- Signale {best_v['model_sigs']}, Extra {best_v['extra']}, Hit Bull {best_v['hits_bull']}/{best_v['hits_bull']+best_v['misses_bull']} ({best_v['hit_rate_bull']:.2f}), Hit Bear {best_v['hits_bear']}/{best_v['hits_bear']+best_v['misses_bear']} ({best_v['hit_rate_bear']:.2f})\n")
        print(f"Report saved: {report_path}")
        print("\nTop-5:")
        print(top[["trial","score","val_f1","oot_f1","hit_rate_bull","hit_rate_bear","model_sigs","extra"]].to_string(index=False))


if __name__=="__main__":
    main()
