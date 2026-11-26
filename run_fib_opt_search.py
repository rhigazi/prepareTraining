#!/usr/bin/env python3
"""run_fib_opt_search.py - Fibonacci features/filter optimization (general)."""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import talib

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN = os.path.join(HERE, "train_turning_points.py")
EXTREMES = os.path.join(HERE, "extremes_tool.py")
PY = sys.executable
RAW_DIR = os.path.join(HERE, "raw_data")
SEARCH_DIR = os.path.join(HERE, "runs", "fib_opt_v1")
OUT_EXT = os.path.join(HERE, "extremes_output_fib_v1")

if HERE not in sys.path:
    sys.path.insert(0, HERE)
import extremes_tool as et
import prepareTraining as pt


def sma_segment_labels(close, high, low):
    s38 = pd.Series(close).rolling(38, min_periods=38).mean().to_numpy()
    s80 = pd.Series(close).rolling(80, min_periods=80).mean().to_numpy()
    diff = s38 - s80
    crosses = [0]
    for i in range(1, len(close)):
        if not (np.isfinite(diff[i-1]) and np.isfinite(diff[i])): continue
        if diff[i-1] == 0: continue
        if np.sign(diff[i]) != np.sign(diff[i-1]) and diff[i] != 0:
            crosses.append(i)
    crosses.append(len(close)-1); crosses = sorted(set(crosses))
    labels = np.zeros(len(close))
    for a,b in zip(crosses, crosses[1:]):
        if b-a < 1: continue
        mid=(a+b)//2
        if not np.isfinite(diff[mid]): continue
        if diff[mid] > 0:
            pos=int(np.nanargmax(high[a:b+1])+a); labels[pos]=-1.0
        else:
            pos=int(np.nanargmin(low[a:b+1])+a); labels[pos]=1.0
    return labels


def expand_labels(labels, tol):
    if tol <= 0: return labels.copy()
    out=labels.copy(); n=len(labels)
    for i in range(n):
        if labels[i]!=0:
            for j in range(max(0,i-tol),min(n,i+tol+1)):
                if out[j]==0: out[j]=labels[i]
    return out


def make_prepared(lookback, tol, dst):
    if os.path.exists(dst): shutil.rmtree(dst)
    os.makedirs(dst, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(RAW_DIR,"*.csv"))):
        df = pd.read_csv(path)
        for col in ["t","o","h","l","c","v"]:
            if col not in df.columns: raise ValueError(f"Missing {col}")
        if "vw" not in df.columns: df["vw"]=df["c"]
        df = pt.sort_and_dedup(df)
        o=df["o"].to_numpy(float); h=df["h"].to_numpy(float); l=df["l"].to_numpy(float)
        c=df["c"].to_numpy(float); v=df["v"].to_numpy(float); n=len(df)
        ticker, timeframe = pt.parse_ticker_timeframe(path)

        sh = pd.Series(h).rolling(lookback, min_periods=lookback).max().to_numpy()
        sl = pd.Series(l).rolling(lookback, min_periods=lookback).min().to_numpy()
        rng = sh - sl
        atr = talib.ATR(h,l,c,timeperiod=14)
        valid_swing = np.isfinite(rng) & (rng>0) & np.isfinite(atr) & (atr>0) & (rng/atr >= 1.0)

        fib_pos = (c - sl) / np.where(rng==0,1.0,rng)
        levels=[0.382,0.5,0.618,0.786]
        feat={}
        feat["feat_fib_pos"]=fib_pos
        for lev in levels:
            lvl_price = sl + lev*rng
            feat[f"feat_fib_dist_{int(lev*1000)}"] = (c - lvl_price)/np.where(rng==0,1.0,rng)
        feat["feat_swing_range_atr"] = rng/np.where(atr==0,1.0,atr)
        feat["feat_dist_swing_high_atr"] = (sh-c)/np.where(atr==0,1.0,atr)
        feat["feat_dist_swing_low_atr"] = (c-sl)/np.where(atr==0,1.0,atr)
        ret1 = np.concatenate([[np.nan], np.diff(c)/np.where(c[:-1]==0,1.0,c[:-1])])
        vol_ratio = v / np.where(pd.Series(v).rolling(20,min_periods=20).mean().to_numpy()==0,1.0,pd.Series(v).rolling(20,min_periods=20).mean().to_numpy())
        feat["feat_ret1"]=ret1
        feat["feat_vol_ratio"]=vol_ratio
        for k in feat:
            feat[k]=np.where(valid_swing, feat[k], np.nan)

        labels = sma_segment_labels(c,h,l)
        labels = expand_labels(labels, tol)

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

        out=pd.DataFrame({
            "meta_t": df["t"].values,
            "meta_ticker": [ticker]*n,
            "meta_timeframe": [timeframe]*n,
            "meta_open": o, "meta_high": h, "meta_low": l, "meta_close": c,
        })
        for k,val in feat.items():
            out[k]=val
        out["label_turn"]=labels
        out["label_max_move_atr"]=label_max_move
        feat_cols=[col for col in out.columns if col.startswith("feat_")]
        out=out.replace([np.inf,-np.inf],np.nan)
        out=out.dropna(subset=feat_cols+["label_turn","label_max_move_atr"]).reset_index(drop=True)
        out["label_turn"]=out["label_turn"].astype(int)
        if out.empty: continue
        stem=os.path.splitext(os.path.basename(path))[0]
        out.to_csv(os.path.join(dst, f"{stem}_prepared.csv"), index=False)
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
    parser.add_argument("--trials",type=int,default=8)
    args=parser.parse_args()

    os.makedirs(SEARCH_DIR,exist_ok=True)
    print("Preparing datasets...")
    data_lb20_tol0=make_prepared(20,0,os.path.join(SEARCH_DIR,"prepared_lb20_tol0"))
    data_lb20_tol1=make_prepared(20,1,os.path.join(SEARCH_DIR,"prepared_lb20_tol1"))

    configs=[
        ("fibv1_01", data_lb20_tol0, ["--hidden-dims","64","32","--dropout","0.35","--class-weight-power","0.5","--learning-rate","5e-4","--cooldown-bars","8","--threshold-min","0.50","--threshold-max","0.60"]),
        ("fibv1_02", data_lb20_tol1, ["--hidden-dims","64","32","--dropout","0.35","--class-weight-power","0.5","--learning-rate","5e-4","--cooldown-bars","8","--threshold-min","0.50","--threshold-max","0.60"]),
        ("fibv1_03", data_lb20_tol0, ["--hidden-dims","96","48","--dropout","0.4","--class-weight-power","0.6","--learning-rate","7e-4","--cooldown-bars","10","--threshold-min","0.55","--threshold-max","0.65"]),
        ("fibv1_04", data_lb20_tol1, ["--hidden-dims","96","48","--dropout","0.4","--class-weight-power","0.6","--learning-rate","7e-4","--cooldown-bars","10","--threshold-min","0.55","--threshold-max","0.65"]),
        ("fibv1_05", data_lb20_tol1, ["--hidden-dims","128","64","--dropout","0.45","--class-weight-power","0.7","--learning-rate","1e-3","--cooldown-bars","8","--threshold-min","0.45","--threshold-max","0.55"]),
        ("fibv1_06", data_lb20_tol0, ["--hidden-dims","64","32","--dropout","0.3","--class-weight-power","0.4","--learning-rate","5e-4","--cooldown-bars","12","--threshold-min","0.50","--threshold-max","0.60"]),
        ("fibv1_07", data_lb20_tol1, ["--hidden-dims","64","32","--dropout","0.35","--class-weight-power","0.5","--learning-rate","5e-4","--cooldown-bars","6","--threshold-min","0.50","--threshold-max","0.60"]),
        ("fibv1_08", data_lb20_tol0, ["--hidden-dims","64","32","--dropout","0.35","--class-weight-power","0.5","--learning-rate","5e-4","--cooldown-bars","10","--threshold-min","0.60","--threshold-max","0.70"]),
    ]
    configs=configs[:args.trials]

    rows=[]
    for name,data_dir,extra in configs:
        try:
            out_dir,val_f1,oot_f1=run_train(name,data_dir,extra,args.epochs)
            v=validate_trial(out_dir)
            score=composite_score(val_f1,oot_f1,v)
            tol=os.path.basename(data_dir).replace("prepared_lb20_tol","")
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
        cmd=[PY,EXTREMES,"--mode","all","--input-dir",RAW_DIR,"--output-dir",OUT_EXT,"--model-dir",best_target,"--tolerance-bars","5","--window-bars","400"]
        subprocess.run(cmd,check=True)
        # report
        def load_summary(d):
            p=os.path.join(d,"reports","sma_validation_summary.csv")
            return pd.read_csv(p) if os.path.exists(p) else None
        opt01=load_summary(os.path.join(HERE,"extremes_output"))
        ml4t=load_summary(os.path.join(HERE,"runs","ml4t_search","best"))
        vis03=load_summary(os.path.join(HERE,"runs","visual_opt","best"))
        fib=load_summary(OUT_EXT)
        best_v=validate_trial(best_target)
        report_path=os.path.join(SEARCH_DIR,"fib_report.md")
        with open(report_path,"w") as f:
            f.write("# Fibonacci Experiment Strand (v1) – Vergleich\n\n")
            f.write("## Top-5 Experimente\n\n")
            f.write(df.head(5)[["trial","label_tol","val_f1","oot_f1","hit_rate_bull","hit_rate_bear","model_sigs","extra","score"]].to_markdown(index=False))
            f.write("\n\n## Bester Lauf\n\n")
            f.write(f"- Trial: {best_name}\n- Score: {df.iloc[0]['score']:.4f}\n- Dir: {best_target}\n")
            f.write(f"- Validierung/Charts: {OUT_EXT}/charts/ (inkl. GOOG_15Min Bars 400–799, AAPL_1Hour Bars 1600–1999)\n\n")
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
            if vis03 is not None:
                v=vis03; v_tot=v["model_signals"].sum(); v_extra=v["extra_signals"].sum()
                v_hb=v["hits_bull"].sum(); v_mb=v["misses_bull"].sum()
                v_hr=v["hits_bear"].sum(); v_mr=v["misses_bear"].sum()
                f.write("## Vergleich vs. vis_03\n\n")
                f.write(f"- vis_03: Signale {v_tot}, Extra {v_extra}, Hit Bull {v_hb}/{v_hb+v_mb} ({v_hb/(v_hb+v_mb):.2f}), Hit Bear {v_hr}/{v_hr+v_mr} ({v_hr/(v_hr+v_mr):.2f})\n")
            if fib is not None:
                fb=fib; f_tot=fb["model_signals"].sum(); f_extra=fb["extra_signals"].sum()
                f_hb=fb["hits_bull"].sum(); f_mb=fb["misses_bull"].sum()
                f_hr=fb["hits_bear"].sum(); f_mr=fb["misses_bear"].sum()
                f.write("## Bester Fibonacci-Kandidat\n\n")
                f.write(f"- Signale {f_tot}, Extra {f_extra}, Hit Bull {f_hb}/{f_hb+f_mb} ({f_hb/(f_hb+f_mb):.2f}), Hit Bear {f_hr}/{f_hr+f_mr} ({f_hr/(f_hr+f_mr):.2f})\n")
            f.write("\n## Kurzfazit\n\n")
            f.write("- Allgemeine Fibonacci-Features (rollierende Swings, Retracement-Niveaus) ohne Lookahead; einheitliche Filter über alle Ticker/Timeframes.\n")
            f.write("- Stichproben-Charts: extremes_output_fib_v1/charts/ (GOOG_15Min Bars 400–799, AAPL_1Hour Bars 1600–1999).\n")
        print(f"Report saved: {report_path}")
        print("\nTop-5:")
        print(df.head(5)[["trial","score","val_f1","oot_f1","hit_rate_bull","hit_rate_bear","model_sigs","extra"]].to_string(index=False))


if __name__=="__main__":
    main()
