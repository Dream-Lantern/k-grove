"""Regenerate checked-in schemas from the single Python source of truth."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from doc_review.schemas import REVIEW,EDIT
root=Path(__file__).parent/'schemas';root.mkdir(exist_ok=True)
for name,value in [('review',REVIEW),('edit-result',EDIT)]:
    (root/(name+'.schema.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
