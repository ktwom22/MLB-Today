from flask import Flask, request, render_template
import pandas as pd
import pulp
import requests
from io import StringIO
import os

app = Flask(__name__)

GOOGLE_SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1aCccCQIU8Z5ve9QM8SrgG50hfD0WYYQmu-Z6fAt0TCw/gviz/tq?tqx=out:csv&gid=130416604"

def clean_data(df):
    df.columns = df.columns.str.strip().str.upper()
    if "PROJECTED POINTS" in df.columns:
        df.rename(columns={"PROJECTED POINTS": "PROJECTE POINTS"}, inplace=True)
    required = {"NAME", "POS", "SALARY", "PROJECTE POINTS", "TEAM"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    df['SALARY'] = df['SALARY'].replace('[\\$,]', '', regex=True).astype(float)
    df['PROJECTE POINTS'] = pd.to_numeric(df['PROJECTE POINTS'], errors='coerce')
    df['POS'] = df['POS'].str.upper().str.strip()
    df['TEAM'] = df['TEAM'].str.upper().str.strip()
    df = df.dropna(subset=['NAME', 'SALARY', 'POS', 'PROJECTE POINTS', 'TEAM'])
    df['IS_HITTER'] = df['POS'] != 'P'
    return df

def generate_lineup(df, excluded_lineups=[], stack_team=None, stack_size=0, exposure_counts=None, max_exposure=None, total_lineups=1):
    prob = pulp.LpProblem("MLB_Lineup", pulp.LpMaximize)
    player_vars = {
        row['NAME']: pulp.LpVariable(row['NAME'], cat='Binary')
        for _, row in df.iterrows()
    }

    prob += pulp.lpSum(player_vars[p] * df.loc[df['NAME'] == p, 'PROJECTE POINTS'].values[0] for p in player_vars)

    total_salary = pulp.lpSum(player_vars[p] * df.loc[df['NAME'] == p, 'SALARY'].values[0] for p in player_vars)
    prob += total_salary <= 50000
    prob += total_salary >= 45000

    prob += pulp.lpSum(player_vars[p] for p in player_vars) == 10

    pos_req = {"P": 2, "C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3}
    for pos, num in pos_req.items():
        eligible = df[df['POS'] == pos]['NAME']
        prob += pulp.lpSum(player_vars[p] for p in eligible if p in player_vars) == num

    hitters = df[df['IS_HITTER']]['NAME']
    prob += pulp.lpSum(player_vars[p] for p in hitters if p in player_vars) >= 8

    if stack_team and stack_size > 0:
        stack_team = stack_team.upper()
        team_players = df[df['TEAM'] == stack_team]['NAME']
        prob += pulp.lpSum(player_vars[p] for p in team_players if p in player_vars) >= stack_size

    for prev_lineup in excluded_lineups:
        prob += pulp.lpSum(player_vars[p] for p in prev_lineup if p in player_vars) <= len(prev_lineup) - 1

    if exposure_counts and max_exposure:
        for player, count in exposure_counts.items():
            if player in player_vars:
                allowed = int(max_exposure * total_lineups)
                if count >= allowed:
                    prob += player_vars[player] == 0

    prob.solve()

    lineup, total_salary_val, total_points_val, selected_players = [], 0, 0, set()
    for p in player_vars:
        if player_vars[p].varValue == 1:
            row = df.loc[df['NAME'] == p].iloc[0]
            lineup.append({
                'Name': p,
                'Position': row['POS'],
                'Salary': row['SALARY'],
                'Points': row['PROJECTE POINTS'],
                'Team': row['TEAM']
            })
            total_salary_val += row['SALARY']
            total_points_val += row['PROJECTE POINTS']
            selected_players.add(p)

    return lineup, total_salary_val, total_points_val, selected_players

@app.route('/', methods=['GET'])
def show_lineups():
    try:
        if not request.args:
            return render_template("index.html", lineups=[], teams=[], count=5, stack_team="", stack_size=0, exposure_pct=100, prompt=True)

        count = int(request.args.get('count', 5))
        stack_team = request.args.get('team', '').strip().upper()
        stack_size = int(request.args.get('stack', 0))
        exposure_pct = float(request.args.get('exposure', 100)) / 100.0

        r = requests.get(GOOGLE_SHEET_CSV_URL)
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        df = clean_data(df)

        all_lineups = []
        excluded_lineups = []
        exposure_counts = {}

        for _ in range(count * 3):
            lineup, sal, pts, selected = generate_lineup(
                df, excluded_lineups, stack_team, stack_size,
                exposure_counts, exposure_pct, count
            )
            if not lineup:
                break
            excluded_lineups.append(selected)
            all_lineups.append({'players': lineup, 'salary': sal, 'points': pts})
            for p in selected:
                exposure_counts[p] = exposure_counts.get(p, 0) + 1
            if len(all_lineups) >= count:
                break

        teams = sorted(df['TEAM'].unique())
        return render_template("index.html", lineups=all_lineups, teams=teams,
                               count=count, stack_team=stack_team,
                               stack_size=stack_size, exposure_pct=int(exposure_pct * 100), prompt=False)

    except Exception as e:
        return render_template("index.html", error=str(e), lineups=[], teams=[],
                               count=5, stack_team="", stack_size=0, exposure_pct=100, prompt=False)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=True)
