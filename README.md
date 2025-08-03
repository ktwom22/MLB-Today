# MLB Lineup Optimizer

A Flask web app that generates optimized MLB lineups based on salary, projected points, and team stacking constraints. Useful for DFS (daily fantasy sports) lineup building.

## 🚀 Features

- Reads MLB player data from a public Google Sheet
- Optimizes lineups using PuLP linear programming
- Lets users customize:
  - Number of lineups
  - Team stack and size
  - Max player exposure %
- Interactive HTML interface via Jinja2 templates

## 🧰 Tech Stack

- Python
- Flask
- Pandas
- PuLP
- HTML + Jinja2
- Google Sheets CSV as data source

## 📦 Installation

```bash
git clone https://github.com/ktwom22/MLB-Today.git
cd MLB-Today
pip install -r requirements.txt
