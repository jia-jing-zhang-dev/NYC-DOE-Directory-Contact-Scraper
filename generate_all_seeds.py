dbns = []

for i in range(1, 1000):
    school = f"Q{i:03d}"
    dbns.append(school)


seed_urls = [
    f"https://www.schools.nyc.gov/schools/{dbn}"
    for dbn in dbns
]


with open("seeds.txt", "w", encoding="utf-8") as f:
    for url in seed_urls:
        f.write(url + "\n")


print(f"🎉 成功生成了 {len(seed_urls)} 所学校的网址到 seeds.txt！")