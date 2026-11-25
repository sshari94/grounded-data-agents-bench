"""Build the synthetic factory database for the grounded-agents experiment.

Everything is synthetic and seeded. No real company data is used.
The schema deliberately contains the traps described in the paper:
terse column names, effective-dated genealogy with rework, retests,
voided and engineering scrap, plant-local time, and a stale snapshot table.

Usage: python gen_db.py --db ../data/factory.duckdb --seed 7
"""
import argparse
import os

import duckdb
import numpy as np
import pandas as pd

START = pd.Timestamp("2026-03-01")
END = pd.Timestamp("2026-06-15")          # exclusive; "today" is 2026-06-15
SNAP_FROZEN_AFTER = pd.Timestamp("2026-04-01")  # stale snapshot stops here

SITES = [(1, "AUS", -5), (2, "BER", 2)]  # site_id, site code, UTC offset in hours
LINES_PER_SITE = 3
PACKS_PER_LINE_DAY = 40
MODS_PER_PACK = 4
CELLS_PER_MOD = 6
N_LOTS = 240
N_SUPPLIERS = 12
SCRAP_REASONS = ["ISO", "WLD", "LEAK", "OCV", "DIM", "CNT", "THM"]


def build(db_path, seed):
    rng = np.random.default_rng(seed)
    if os.path.exists(db_path):
        os.remove(db_path)
    con = duckdb.connect(db_path)

    site = pd.DataFrame(SITES, columns=["site_id", "site_cd", "utc_ofst_h"])
    lines = []
    for sid, scd, _ in SITES:
        for k in range(LINES_PER_SITE):
            lines.append((len(lines) + 1, sid, f"{scd}-L{k + 1}"))
    line = pd.DataFrame(lines, columns=["ln_id", "site_id", "ln_nm"])
    ofst = dict(zip(site.site_id, site.utc_ofst_h))
    ln_ofst = {r.ln_id: ofst[r.site_id] for r in line.itertuples()}

    lot = pd.DataFrame({
        "lot_id": np.arange(1, N_LOTS + 1, dtype=np.int32),
        "supp_id": rng.integers(1, N_SUPPLIERS + 1, N_LOTS).astype(np.int16),
        "matl_cd": rng.choice(["NMC-A", "NMC-B", "LFP-A"], N_LOTS),
    })

    # ---- packs: build timestamps are stored in UTC ----
    days = pd.date_range(START, END - pd.Timedelta(days=1), freq="D")
    rows = []
    for ln in line.ln_id:
        n = len(days) * PACKS_PER_LINE_DAY
        local_day = np.repeat(days.values, PACKS_PER_LINE_DAY)
        sec = rng.integers(0, 86400, n)
        local_ts = local_day + sec.astype("timedelta64[s]")
        utc_ts = local_ts - np.timedelta64(int(ln_ofst[ln]), "h")
        rows.append(pd.DataFrame({"ln_id": ln, "bld_ts_utc": utc_ts}))
    pack = pd.concat(rows, ignore_index=True).sort_values("bld_ts_utc").reset_index(drop=True)
    pack.insert(0, "pack_sn", [f"P{i:07d}" for i in range(1, len(pack) + 1)])
    pack["prod_cd"] = rng.choice(["PK-75", "PK-90"], len(pack))

    # ---- modules and cells (original build) ----
    n_pack = len(pack)
    mod = pd.DataFrame({
        "mod_sn": [f"M{i:08d}" for i in range(1, n_pack * MODS_PER_PACK + 1)],
        "pack_sn": np.repeat(pack.pack_sn.values, MODS_PER_PACK),
        "ts": np.repeat(pack.bld_ts_utc.values, MODS_PER_PACK) - np.timedelta64(2, "h"),
    })
    # each module draws all its cells from one lot, picked from a window of lots
    # current at build time, so modules in the same pack usually use different lots
    base_lot = (np.arange(len(mod)) * N_LOTS // len(mod)) + 1 + rng.integers(0, 10, len(mod))
    cell_lot = np.repeat(base_lot, CELLS_PER_MOD)
    cell_lot = np.clip(cell_lot, 1, N_LOTS)
    cell = pd.DataFrame({
        "cell_sn": [f"C{i:09d}" for i in range(1, len(mod) * CELLS_PER_MOD + 1)],
        "lot_id": cell_lot.astype(np.int32),
        "mod_sn": np.repeat(mod.mod_sn.values, CELLS_PER_MOD),
        "ts": np.repeat(mod.ts.values, CELLS_PER_MOD) - np.timedelta64(1, "h"),
    })

    links = [
        pd.DataFrame({"child_sn": cell.cell_sn, "child_lvl": "CELL", "parent_sn": cell.mod_sn,
                      "parent_lvl": "MOD", "vld_from": cell.ts, "vld_to": pd.NaT}),
        pd.DataFrame({"child_sn": mod.mod_sn, "child_lvl": "MOD", "parent_sn": mod.pack_sn,
                      "parent_lvl": "PACK", "vld_from": mod.ts, "vld_to": pd.NaT}),
    ]

    # ---- final test with retests ----
    tst = []
    fate = {}
    for p, ln, ts in zip(pack.pack_sn, pack.ln_id, pack.bld_ts_utc):
        t = ts + pd.Timedelta(minutes=int(rng.integers(20, 90)))
        p_first_fail = 0.06 + 0.03 * (ln % 3)
        attempts = []
        if rng.random() >= p_first_fail:
            attempts = ["P"]
        else:
            attempts = ["F"]
            for _ in range(2):
                if rng.random() < 0.65:
                    attempts.append("P")
                    break
                attempts.append("F")
        for k, r in enumerate(attempts, 1):
            tst.append((p, ln, t + pd.Timedelta(minutes=45 * (k - 1)), k, r))
        fate[p] = (attempts[-1], t + pd.Timedelta(minutes=45 * len(attempts)))
    tst = pd.DataFrame(tst, columns=["pack_sn", "ln_id", "tst_ts_utc", "atmpt_no", "rslt_cd"])
    tst.insert(0, "tst_id", np.arange(1, len(tst) + 1, dtype=np.int64))
    tst.insert(2, "stn_id", (tst.ln_id * 100 + 20).astype(np.int32))

    # ---- rework: swap one module in some passed packs (effective-dated genealogy) ----
    rwk, new_mods, new_cells, mod_scrap = [], [], [], []
    passed = [p for p, (r, _) in fate.items() if r == "P"]
    rw_packs = rng.choice(passed, size=int(0.03 * len(passed)), replace=False)
    pack_idx = pack.set_index("pack_sn")
    mods_of = mod.groupby("pack_sn").mod_sn.apply(list)
    mod_end = links[1].set_index("child_sn")
    next_mod = len(mod) + 1
    next_cell = len(cell) + 1
    for p in rw_packs:
        r_ts = fate[p][1] + pd.Timedelta(hours=int(rng.integers(2, 72)))
        if r_ts >= END:
            continue
        old = rng.choice(mods_of[p])
        mod_end.loc[old, "vld_to"] = r_ts
        nm = f"M{next_mod:08d}"; next_mod += 1
        new_mods.append((nm, "MOD", p, "PACK", r_ts, pd.NaT))
        lot_new = int(rng.integers(1, N_LOTS + 1))
        for _ in range(CELLS_PER_MOD):
            cs = f"C{next_cell:09d}"; next_cell += 1
            new_cells.append((cs, lot_new, nm, r_ts - pd.Timedelta(hours=1)))
        rwk.append((p, r_ts, "MOD_SWAP", old, nm))
        mod_scrap.append((old, "MOD", int(pack_idx.loc[p, "ln_id"]), r_ts, "WLD"))
    links[1] = mod_end.reset_index()
    links.append(pd.DataFrame(new_mods, columns=links[1].columns))
    nc = pd.DataFrame(new_cells, columns=["cell_sn", "lot_id", "mod_sn", "ts"])
    links.append(pd.DataFrame({"child_sn": nc.cell_sn, "child_lvl": "CELL", "parent_sn": nc.mod_sn,
                               "parent_lvl": "MOD", "vld_from": nc.ts, "vld_to": pd.NaT}))
    gnl = pd.concat(links, ignore_index=True)
    cell_all = pd.concat([cell[["cell_sn", "lot_id"]], nc[["cell_sn", "lot_id"]]], ignore_index=True)
    rwk = pd.DataFrame(rwk, columns=["pack_sn", "rwk_ts_utc", "rwk_typ", "old_sn", "new_sn"])
    rwk.insert(0, "rwk_id", np.arange(1, len(rwk) + 1, dtype=np.int32))

    # ---- scrap events: production scrap, engineering scrap, voids ----
    sc = []
    for p, (r, t) in fate.items():
        if r == "F" and rng.random() < 0.85:
            ln = int(pack_idx.loc[p, "ln_id"])
            w = np.array([5, 4, 3, 3, 2, 1, 1], float) + rng.random(7) * 0.5 + (ln % 3) * np.eye(7)[ln % 7]
            sc.append((p, "PACK", ln, t + pd.Timedelta(hours=1), rng.choice(SCRAP_REASONS, p=w / w.sum()), 0, 0))
    eng = rng.choice(passed, size=int(0.004 * len(passed)), replace=False)
    for p in eng:
        t = fate[p][1] + pd.Timedelta(hours=3)
        if t < END:
            sc.append((p, "PACK", int(pack_idx.loc[p, "ln_id"]), t, "ENG", 1, 0))
    for m, lvl, ln, t, rs in mod_scrap:
        sc.append((m, lvl, ln, t, rs, 0, 0))
    scr = pd.DataFrame(sc, columns=["sn", "lvl", "ln_id", "scrp_ts_utc", "rsn_cd", "eng_flg", "vd_flg"])
    scr = scr[scr.scrp_ts_utc < END]
    # about 15% of pack scrap rows were posted twice by mistake; the duplicate is voided
    dup = scr[(scr.lvl == "PACK") & (scr.eng_flg == 0)].sample(frac=0.15, random_state=seed).copy()
    dup["vd_flg"] = 1
    dup["scrp_ts_utc"] = dup.scrp_ts_utc + pd.Timedelta(minutes=10)
    scr = pd.concat([scr, dup], ignore_index=True).sort_values("scrp_ts_utc").reset_index(drop=True)
    scr.insert(0, "scrp_id", np.arange(1, len(scr) + 1, dtype=np.int64))
    scr["scrp_q"] = 1

    for name, df in [("dim_site", site), ("dim_ln", line), ("dim_lot", lot), ("pk_bld", pack),
                     ("cel_mst", cell_all), ("gnl_lnk", gnl), ("tst_rslt", tst),
                     ("rwk_evt", rwk), ("scrp_evt", scr)]:
        con.register("tmp_df", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM tmp_df")
        con.unregister("tmp_df")

    # governed daily aggregate (current) and the stale legacy snapshot
    con.execute("""
        CREATE TABLE agg_scrp_dly AS
        SELECT CAST(s.scrp_ts_utc + to_hours(CAST(si.utc_ofst_h AS BIGINT)) AS DATE) AS dt_lcl,
               s.ln_id, COUNT(DISTINCT s.sn) AS scrp_cnt
        FROM scrp_evt s JOIN dim_ln l USING (ln_id) JOIN dim_site si USING (site_id)
        WHERE s.lvl = 'PACK' AND s.eng_flg = 0 AND s.vd_flg = 0
        GROUP BY 1, 2""")
    con.execute(f"""
        CREATE TABLE scrp_dly_snap AS
        SELECT CAST(scrp_ts_utc AS DATE) AS dt, ln_id, SUM(scrp_q) AS scrp_cnt
        FROM scrp_evt
        WHERE scrp_ts_utc < TIMESTAMP '{SNAP_FROZEN_AFTER}'
        GROUP BY 1, 2""")
    con.close()
    print(f"built {db_path}: packs={len(pack)} cells={len(cell_all)} tests={len(tst)} "
          f"rework={len(rwk)} scrap_rows={len(scr)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(os.path.dirname(__file__), "..", "data", "factory.duckdb"))
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(a.db)), exist_ok=True)
    build(a.db, a.seed)
