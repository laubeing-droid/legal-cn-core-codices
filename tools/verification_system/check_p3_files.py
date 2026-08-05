import json

from config import CHECKPOINT_INPUT


def main() -> None:
    with CHECKPOINT_INPUT.open("r", encoding="utf-8") as file:
        data = json.load(file)
    results = data.get("results", [])

    dir_counts = {}
    for result in results:
        local_path = result.get("local_path", "")
        parts = local_path.replace("\\", "/").split("/")
        dir_name = parts[0] if parts else ""
        dir_counts[dir_name] = dir_counts.get(dir_name, 0) + 1

    print("目录分布:")
    for dir_name, count in sorted(dir_counts.items()):
        print(f"  {dir_name}: {count}")

    p3_files = [
        result
        for result in results
        if result.get("local_path", "")
        .replace("\\", "/")
        .startswith(("05_地方立法", "06_规章"))
    ]
    print(f"\nP3适用文件: {len(p3_files)}")
    if p3_files:
        print("前3个:")
        for result in p3_files[:3]:
            print(f'  {result.get("local_path", "")[:60]}')
            print(f'    URL: {result.get("official_url", "")[:50]}')


if __name__ == "__main__":
    main()
