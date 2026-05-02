import argparse
import requests

# 台灣 5/4 的兩場 G7 = 美東 5/3
GAME_DATE_1 = "20260503"

ESPN_URL_1 = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={GAME_DATE_1}&seasontype=3"

TEAM_MAP = {
    "Orlando Magic": "魔術",
    "Detroit Pistons": "活塞",
    "Cleveland Cavaliers": "騎士",
    "Toronto Raptors": "暴龍",
    "Los Angeles Lakers": "湖人",
    "Houston Rockets": "火箭",
    "Oklahoma City Thunder": "雷霆",
    "Phoenix Suns": "太陽",
    "Boston Celtics": "塞爾提克",
    "Philadelphia 76ers": "76人",
    "New York Knicks": "尼克",
    "Atlanta Hawks": "老鷹",
    "Minnesota Timberwolves": "灰狼",
    "Denver Nuggets": "金塊",
    "San Antonio Spurs": "馬刺",
    "Portland Trail Blazers": "拓荒者",
}

# MATCHES 的 key = match id (0,1)
# a = Team A（第一隊）, b = Team B（第二隊）
# 對應 Firestore 欄位: r{id}=勝隊, a{id}=A隊分數, b{id}=B隊分數, m{id}=勝分差距
MATCHES = {
    0: ("魔術", "活塞"),     # ORL @ DET G7 (美東 5/3)
    1: ("暴龍", "騎士"),     # TOR @ CLE G7 (美東 5/3)
}

FIRESTORE_URL = (
    "https://firestore.googleapis.com/v1/projects/"
    "gen-lang-client-0737444461/databases/(default)/"
    "documents/game_results/nba_0504"
)

def margin_bucket(diff):
    """將分差轉換為 0/1/2（對應 ≤10 / 11-20 / 21+）"""
    if diff <= 10:
        return 0
    elif diff <= 20:
        return 1
    else:
        return 2

def get_result(event):
    if event["status"]["type"]["name"] != "STATUS_FINAL":
        return None, None, None
    comps = event["competitions"][0]["competitors"]
    winner = None
    score_map = {}
    for comp in comps:
        team_name = TEAM_MAP.get(comp["team"]["displayName"])
        score_map[team_name] = int(comp.get("score", 0))
        if comp.get("winner", False):
            winner = team_name
    return winner, score_map, comps

def parse_args():
    parser = argparse.ArgumentParser(
        description="Update NBA 5/4 prediction results from ESPN into Firestore."
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write finished-game results to Firestore. Without this flag, only print a dry run.",
    )
    parser.add_argument(
        "--include-empty",
        action="store_true",
        help="Also write null values for unfinished games. Default skips unfinished games.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    results = {i: {"winner": None, "scoreA": None, "scoreB": None, "margin": None} for i in range(len(MATCHES))}

    # 抓 5/3 美東賽程（台灣 5/4 的兩場 G7）
    all_events = []
    data = requests.get(ESPN_URL_1, timeout=10).json()
    all_events.extend(data.get("events", []))

    for event in all_events:
        comps = event["competitions"][0]["competitors"]
        team_names = {TEAM_MAP.get(c["team"]["displayName"]) for c in comps}

        for mid, (teamA, teamB) in MATCHES.items():
            if team_names == {teamA, teamB}:
                winner, score_map, _ = get_result(event)
                if winner and score_map:
                    sA = score_map.get(teamA, 0)
                    sB = score_map.get(teamB, 0)
                    diff = abs(sA - sB)
                    results[mid] = {
                        "winner": winner,
                        "scoreA": sA,
                        "scoreB": sB,
                        "margin": margin_bucket(diff)
                    }
                break

    print("ESPN results:", results)

    fields = {}
    mask_parts = []
    for i in range(len(MATCHES)):
        r = results[i]
        if not args.include_empty and not r["winner"]:
            continue
        fields[f"r{i}"] = {"stringValue": r["winner"]} if r["winner"] else {"nullValue": None}
        fields[f"a{i}"] = {"integerValue": str(r["scoreA"])} if r["scoreA"] is not None else {"nullValue": None}
        fields[f"b{i}"] = {"integerValue": str(r["scoreB"])} if r["scoreB"] is not None else {"nullValue": None}
        fields[f"m{i}"] = {"integerValue": str(r["margin"])} if r["margin"] is not None else {"nullValue": None}
        mask_parts += [f"r{i}", f"a{i}", f"b{i}", f"m{i}"]

    if not fields:
        print("No finished games to update.")
        return

    print("Fields prepared:", ", ".join(mask_parts))
    if not args.write:
        print("Dry run only. Re-run with --write to update Firestore.")
        return

    mask = "&".join(f"updateMask.fieldPaths={p}" for p in mask_parts)
    resp = requests.patch(f"{FIRESTORE_URL}?{mask}", json={"fields": fields}, timeout=10)
    if resp.status_code == 200:
        print("Firestore update succeeded.")
    else:
        print(f"Update failed {resp.status_code}: {resp.text}")

if __name__ == "__main__":
    main()
