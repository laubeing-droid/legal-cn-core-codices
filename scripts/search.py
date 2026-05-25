#!/usr/bin/env python3
"""Search all laws by keyword, article number, or domain. Cross-platform."""
import json, os, re, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATS = ["laws", "interpretations", "guidance", "regulations"]

def search(query, categories=None):
    cats = categories or CATS
    results = []
    for cat in cats:
        d = os.path.join(REPO, cat)
        if not os.path.isdir(d): continue
        for fname in os.listdir(d):
            if not fname.endswith(".json"): continue
            path = os.path.join(d, fname)
            with open(path, "r", encoding="utf-8") as f:
                j = json.load(f)
            name = j.get("name", j.get("title", ""))
            arts = j.get("articles", [])
            
            # Search in article text
            for a in arts:
                text = a.get("text", a.get("content", ""))
                if query.lower() in text.lower():
                    aid = a.get("id", a.get("article_id", "?"))
                    # Show snippet
                    idx = text.lower().find(query.lower())
                    start = max(0, idx - 30)
                    end = min(len(text), idx + len(query) + 80)
                    snippet = text[start:end]
                    results.append({
                        "file": f"{cat}/{fname}",
                        "name": name,
                        "article": str(aid),
                        "snippet": snippet,
                    })
    return results

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python search.py <keyword> [--laws|--all]")
        print("Example: python search.py '不可靠实体清单'")
        sys.exit(1)
    
    query = sys.argv[1]
    cats = CATS if "--all" in sys.argv else ["laws", "interpretations"]
    
    results = search(query, cats)
    print(f"\n{query}: {len(results)} matches\n")
    for r in results[:50]:
        print(f"[{r['file']}] 第{r['article']}条")
        print(f"  {r['snippet']}")
        print()
    if len(results) > 50:
        print(f"... and {len(results)-50} more")
