import json

with open('D:/legal-references/90_项目任务记录/全文全量核对_20260731_221821/checkpoints/batch_checkpoint.json', 'r') as f:
    data = json.load(f)
results = data.get('results', [])

# 统计各目录文件数
dir_counts = {}
for r in results:
    path = r.get('local_path', '')
    parts = path.replace('\\', '/').split('/')
    dir_name = parts[0] if parts else ''
    dir_counts[dir_name] = dir_counts.get(dir_name, 0) + 1

print('目录分布:')
for d, c in sorted(dir_counts.items()):
    print(f'  {d}: {c}')

# P3适用的文件
p3_files = [r for r in results if r.get('local_path', '').replace('\\', '/').startswith(('05_地方立法', '06_规章'))]
print(f'\nP3适用文件: {len(p3_files)}')
if p3_files:
    print('前3个:')
    for r in p3_files[:3]:
        print(f'  {r.get("local_path", "")[:60]}')
        print(f'    URL: {r.get("official_url", "")[:50]}')
