"""Export challenge, item and battle-state messages for a selected battle; no login data."""
import argparse,json,os,sqlite3
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--battle',required=True,type=int);p.add_argument('--fixed',action='store_true');args=p.parse_args()
base=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'AI-TikTok-LIVE-Analyzer'
dbpath=base/('capture_fixed' if args.fixed else 'capture')/'battle_dataset/battles.sqlite3'
with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True) as db:
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='battle_timeline'").fetchone()
    rows=db.execute("SELECT unique_id,received_at,payload,kind FROM battle_timeline WHERE battle_id=? ORDER BY received_at",(args.battle,)).fetchall() if exists else []
result=[{'unique_id':u,'received_at':t,'kind':kind,'event':json.loads(raw)} for u,t,raw,kind in rows]
output=Path(f'challenge_debug_{args.battle}.json');output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'{output.resolve()} : {len(result)} events')
