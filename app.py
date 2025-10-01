from flask import Flask, request, render_template_string, send_from_directory
import pandas as pd
import pulp
import requests
from io import StringIO
import os

app = Flask(__name__, static_folder='static', template_folder='templates')

GOOGLE_SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vS5VtlWh53WkD4Rqfh55pRir1QSEPZsbLjMSL5M1y8N0RyN6Rc069tkXDpTMjgwgL7dG31NhBWBwoD9/pub?gid=454725640&single=true&output=csv"
SALARY_CAP = 50000

PLAYER_POOL_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>MLB Player Pool</title>
<style>
body { font-family: 'Segoe UI', Tahoma, sans-serif; margin: 20px; background: #f5f6fa; color: #2c3e50; }
h1 { color: #2c3e50; margin-bottom: 10px; }
.card { background: white; border-radius: 8px; padding: 20px; box-shadow: 0 2px 6px rgba(0,0,0,0.1); margin-bottom: 20px; }
table { border-collapse: collapse; width: 100%; margin-top: 10px; }
th, td { border: 1px solid #ddd; padding: 8px; text-align: center; }
th { background-color: #34495e; color: white; }
tr:nth-child(even) { background-color: #f9f9f9; }
tr:hover { background-color: #ecf0f1; }
form { margin-top: 15px; }
input[type=checkbox], input[type=radio], input[type=number] { transform: scale(1.1); margin: 2px; }
button { padding: 10px 16px; background-color: #27ae60; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 14px; }
button:hover { background-color: #2ecc71; }
label { font-weight: 500; margin-right: 10px; }
select { font-size: 14px; padding: 4px 8px; margin-left: 10px; }
</style>
</head>
<body>
<div class="card">
<h1>MLB Player Pool</h1>
<p>Total Players: {{ players|length }}</p>
<form method="post" action="/lineups">
<input type="hidden" name="count" value="5">
<label>Team Stack:</label>
<select name="team">
  <option value="">None</option>
  {% for t in teams %}
    <option value="{{ t }}">{{ t }}</option>
  {% endfor %}
</select>
<label>Stack Size:</label>
<input type="number" name="stack" value="0" min="0" max="10">
<label>Max Exposure (%):</label>
<input type="number" name="exposure" value="100" min="1" max="100">
<br><br>
<table>
<thead>
<tr>
<th>Name</th>
<th>Position</th>
<th>Team</th>
<th>Salary</th>
<th>Proj. Points</th>
<th>Lock</th>
<th>Exclude</th>
</tr>
</thead>
<tbody>
{% for p in players %}
<tr>
<td>{{ p.Name }}</td>
<td>{{ p.Position }}</td>
<td>{{ p.Team }}</td>
<td>${{ "{:,.0f}".format(p.Salary) }}</td>
<td>{{ "%.2f"|format(p.Points) }}</td>
<td><input type="radio" name="lock_player" value="{{ p.Name }}"></td>
<td><input type="checkbox" name="exclude_players" value="{{ p.Name }}"></td>
</tr>
{% endfor %}
</tbody>
</table>
<br>
<button type="submit">⚡ Generate Lineups</button>
</form>
</div>
</body>
</html>
"""

LINEUP_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>Generated Lineups</title>
<style>
body { font-family: 'Segoe UI', Tahoma, sans-serif; margin: 20px; background: #f5f6fa; color: #2c3e50; }
h1 { color: #2c3e50; margin-bottom: 20px; }
.card { background: white; border-radius: 10px; padding: 20px; box-shadow: 0 3px 8px rgba(0,0,0,0.1); margin-bottom: 25px; transition: transform 0.1s ease-in-out; }
.card:hover { transform: translateY(-2px); }
table { border-collapse: collapse; width: 100%; margin-top: 10px; }
th, td { border: 1px solid #ddd; padding: 8px; text-align: center; }
th { background-color: #34495e; color: white; }
button { padding: 10px 16px; background-color: #3498db; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 14px; }
button:hover { background-color: #2980b9; }
</style>
</head>
<body>
<h1>Generated Lineups</h1>
{% if error %}
<p style="color:red;">{{ error }}</p>
{% endif %}
{% for lu in lineups %}
<div class="card">
<h2>Lineup {{ loop.index }}</h2>
<p><strong>Salary:</strong> ${{ "{:,.0f}".format(lu.salary) }} | 
<strong>Projected:</strong> {{ "%.2f"|format(lu.points) }}</p>
<table>
<tr><th>Position</th><th>Name</th><th>Team</th><th>Salary</th><th>Proj. Points</th></tr>
{% for p in lu.players %}
<tr>
<td>{{ p.Position }}</td>
<td>{{ p.Name }}</td>
<td>{{ p.Team }}</td>
<td>${{ "{:,.0f}".format(p.Salary) }}</td>
<td>{{ "%.2f"|format(p.Points) }}</td>
</tr>
{% endfor %}
</table>
</div>
{% endfor %}
<form action="/" method="get">
    <button type="submit">⬅ Back to Player Pool</button>
</form>
</body>
</html>
"""

def clean_data(df):
    df.columns = df.columns.str.strip().str.upper()
    required = {"NAME", "POS", "SALARY", "PROJECTED POINTS", "TEAM"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    # Remove rows where 'NAME' equals 'NAME' (header as data)
    df = df[df['NAME'].str.upper() != 'NAME']
    # Remove rows where 'SALARY' equals 'SALARY' (header as data)
    df = df[df['SALARY'].astype(str).str.upper() != 'SALARY']
    # Remove rows where 'SALARY' is not a valid number
    df = df[df['SALARY'].astype(str).str.replace('[\\$,]', '', regex=True).str.replace('.', '', 1).str.isnumeric()]
    df['SALARY'] = df['SALARY'].replace('[\\$,]', '', regex=True).astype(float)
    df['PROJECTED POINTS'] = pd.to_numeric(df['PROJECTED POINTS'], errors='coerce')
    df['POS'] = df['POS'].str.upper().str.strip()
    df['TEAM'] = df['TEAM'].str.upper().str.strip()
    df = df.copy()
    df = df.dropna(subset=['NAME', 'SALARY', 'POS', 'PROJECTED POINTS', 'TEAM'])
    df.loc[:, 'IS_HITTER'] = df['POS'] != 'P'
    df = df.rename(columns={'NAME': 'Name', 'POS': 'Position', 'SALARY': 'Salary',
                            'PROJECTED POINTS': 'Points', 'TEAM': 'Team'})
    return df

def order_lineup(lineup):
    position_order = ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]
    ordered = []
    used_names = set()
    for pos in position_order:
        for p in lineup:
            if p['Position'] == pos and p['Name'] not in used_names:
                ordered.append(p)
                used_names.add(p['Name'])
                break
    for p in lineup:
        if p['Name'] not in used_names:
            ordered.append(p)
    return ordered

def generate_lineup(df, excluded_lineups=[], stack_team=None, stack_size=0, exposure_counts=None, max_exposure=None,
                    total_lineups=1, lock_player=None):
    prob = pulp.LpProblem("MLB_Lineup", pulp.LpMaximize)
    player_vars = {row['Name']: pulp.LpVariable(row['Name'], cat='Binary') for _, row in df.iterrows()}
    prob += pulp.lpSum(player_vars[p] * df.loc[df['Name'] == p, 'Points'].values[0] for p in player_vars)
    total_salary = pulp.lpSum(player_vars[p] * df.loc[df['Name'] == p, 'Salary'].values[0] for p in player_vars)
    prob += total_salary <= SALARY_CAP
    prob += total_salary >= 45000
    prob += pulp.lpSum(player_vars[p] for p in player_vars) == 10
    pos_req = {"P": 2, "C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3}
    for pos, num in pos_req.items():
        eligible = df[df['Position'] == pos]['Name']
        prob += pulp.lpSum(player_vars[p] for p in eligible if p in player_vars) == num
    hitters = df[df['Position'] != 'P']['Name']
    prob += pulp.lpSum(player_vars[p] for p in hitters if p in player_vars) >= 8
    if stack_team and stack_size > 0:
        stack_team = stack_team.upper()
        team_players = df[df['Team'] == stack_team]['Name']
        prob += pulp.lpSum(player_vars[p] for p in team_players if p in player_vars) >= stack_size
    for prev_lineup in excluded_lineups:
        prob += pulp.lpSum(player_vars[p] for p in prev_lineup if p in player_vars) <= len(prev_lineup) - 1
    if exposure_counts and max_exposure:
        for player, count in exposure_counts.items():
            if player in player_vars:
                allowed = int(max_exposure * total_lineups)
                if count >= allowed:
                    prob += player_vars[player] == 0
    if lock_player and lock_player in player_vars:
        prob += player_vars[lock_player] == 1
    prob.solve()
    lineup, total_salary_val, total_points_val, selected_players = [], 0, 0, set()
    for p in player_vars:
        if player_vars[p].varValue == 1:
            row = df.loc[df['Name'] == p].iloc[0]
            lineup.append({
                'Name': p,
                'Position': row['Position'],
                'Salary': row['Salary'],
                'Points': round(row['Points'], 2),
                'Team': row['Team']
            })
            total_salary_val += row['Salary']
            total_points_val += row['Points']
            selected_players.add(p)
    lineup = order_lineup(lineup)
    return lineup, total_salary_val, round(total_points_val, 2), selected_players

@app.route('/', methods=['GET'])
def player_pool():
    try:
        r = requests.get(GOOGLE_SHEET_CSV_URL)
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        df = clean_data(df)
        teams = sorted(df['Team'].unique())
        players = df.to_dict(orient="records")
        return render_template_string(PLAYER_POOL_TEMPLATE, players=players, teams=teams)
    except Exception as e:
        return f"<p>Error loading player pool: {e}</p>"

@app.route('/lineups', methods=['POST'])
def generate_lineups():
    try:
        r = requests.get(GOOGLE_SHEET_CSV_URL)
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        df = clean_data(df)
        teams = sorted(df['Team'].unique())
        count = int(request.form.get('count', 5))
        stack_team = request.form.get('team', '').strip().upper()
        stack_size = int(request.form.get('stack', 0))
        exposure_pct = float(request.form.get('exposure', 100)) / 100.0
        lock_player = request.form.get('lock_player', None)
        exclude_players = request.form.getlist('exclude_players')
        if exclude_players:
            df = df[~df['Name'].isin(exclude_players)]
        if df.empty:
            raise ValueError("No players available after exclusions.")
        all_lineups = []
        excluded_lineups = []
        exposure_counts = {}
        for _ in range(count * 3):
            lineup, sal, pts, selected = generate_lineup(
                df, excluded_lineups, stack_team, stack_size,
                exposure_counts, exposure_pct, count, lock_player
            )
            if not lineup:
                break
            excluded_lineups.append(list(selected))
            all_lineups.append({'players': lineup, 'salary': sal, 'points': pts})
            for p in selected:
                exposure_counts[p] = exposure_counts.get(p, 0) + 1
            if len(all_lineups) >= count:
                break
        if not all_lineups:
            return render_template_string(LINEUP_TEMPLATE, lineups=[], error="Could not generate lineups with these selections.")
        return render_template_string(LINEUP_TEMPLATE, lineups=all_lineups, error=None)
    except Exception as e:
        return render_template_string(LINEUP_TEMPLATE, lineups=[], error=str(e))

@app.route('/style.css')
def test_file():
    return app.send_static_file('style.css')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=True)