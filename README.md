# Sports Score Ticker for Windows

**NHL · NFL · MLB · NBA · Bundesliga · F1** · Version 2.7.0 (see `CHANGELOG.md` for what changed in each version)

An always-on-top bar that scrolls every game for the day in the league you
pick. It moves continuously from left to right and wraps around in a seamless
loop. Each game shows both teams' logos, the score, and the status: live
period/inning/minute, kickoff time, or final. Click any game to open its full
stats and the league standings. Once a game is over, its stats window has buttons that play the
highlight video from each team's official YouTube channel.

The ticker reserves its strip of the screen the same way the Windows taskbar
does, so nothing gets hidden behind it: maximized windows stop at its edge.

## Installing

Run **`SportsTicker_Setup.exe`** and follow the wizard. On the
**Choose Components** page you can pick:

- **Desktop icon:** puts a Sports Ticker icon on your desktop (on by default).
- **Start menu shortcuts:** adds Sports Ticker and its uninstaller to the
  Start menu (on by default).
- **Start Sports Ticker when Windows starts** (off by default).

Setup installs just for you, so it doesn't need administrator rights. If Python
isn't on your PC, it offers to install it for you. The last page can start the
ticker right away. To update later, run the newer `SportsTicker_Setup.exe`; it
replaces the old version and keeps your settings. To uninstall, use
**Settings > Apps** or **Start menu > Sports Ticker > Uninstall Sports Ticker**.

Windows may show a blue **"Windows protected your PC"** box the first time,
because the installer isn't code-signed. Click **More info**, then **Run anyway**.

### Running without installing

You can also run it straight from the folder: double-click
**`Start Sports Ticker.bat`**.

The ticker runs on Python (free, from python.org). If it isn't on your PC yet,
the launcher offers to install it for you: press **Y**, wait about a minute,
and the ticker starts. No administrator rights are needed. If the automatic
install isn't available on your PC, it opens the python.org download page;
install from there (tick **"Add python.exe to PATH"** on the first screen) and
double-click the launcher again.

**Want a single .exe instead?** Double-click **`Build EXE.bat`** once. It
creates `dist\SportsTicker.exe`, which runs on any Windows PC without Python.

**Start with Windows** (when not using the installer): press `Win + R`, type
`shell:startup`, and put a shortcut to `Start Sports Ticker.bat` (or
`SportsTicker.exe`) in that folder.

**Building the installer yourself:** install NSIS 3, then run
`makensis -DVERSION=2.7.0 installer\SportsTicker.nsi`. The script is in the
`installer` folder.

**Coming from the NHL-only ticker?** Close it with its X first, then delete its
folder (and its startup shortcut, if you made one). This version includes the NHL.

## Using the ticker

| Action | What it does |
|---|---|
| Click the league logo (left end) | Drop-down to switch between NHL, NFL, MLB, NBA, Bundesliga and F1 |
| Click a game | Opens the game's stats window |
| Hover over the bar | Pauses scrolling |
| Mouse wheel | Scrolls through games by hand |
| Right-click | Settings: league, refresh, previous/next day, scroll on/off, speed, direction, position, always-on-top, exit |
| Drag the league logo | Moves the bar between the top and bottom of the screen |
| Right-click → F1 live timing sign-in… | Connects F1 races to F1's official live timing for exact gaps (optional) |
| Right-click → What's new… | Shows the changelog; the version number is at the bottom of the menu |
| ↻ at the right end | Refresh now |
| **X** at the far right | Close the ticker |

The ticker remembers the league you picked. Every league opens on **today's
date** from your PC's calendar, and the bar rolls over to the new day on its
own at midnight. Games from the night before that are still going stay on the
bar until they finish. Use Previous/Next day in the right-click menu to look at
other dates. Live games come first, then upcoming games, then finals. Scores
refresh every 20 seconds while any game is live and every 2 minutes otherwise.

When a league has nothing scheduled, the bar says so: "No NBA games today", or
"No MLB games on Sat Nov 7" when you're looking at another day. When the feed lists upcoming dates, it also shows when the next
games are, for example "Next games: Tue Nov 3".

## F1

F1 works a little differently, because it's races rather than games:

- **The ticker** shows the latest race: its name and date, then every finisher
  in order: position (gold, silver and bronze for the podium), team color,
  driver code, and gap to the winner (or DNF). A purple dot marks the fastest
  lap. At the end, a **NEXT** chip shows the upcoming race and its start time
  in your time zone.
- **Click any F1 chip** for the race window:
  - The header shows the winner and fastest lap, with a **Race highlights**
    button that finds the race highlights on the official Formula 1 YouTube
    channel.
  - Tabs: race results (grid, positions gained, laps, time or status, points,
    fastest laps), sprint (on sprint weekends), qualifying (Q1/Q2/Q3), driver
    standings, constructor standings, and the weekend schedule.
- **Click the NEXT chip** to see the upcoming weekend's schedule (practice,
  sprint, qualifying, race) in your local time, plus the current standings.
- In the right-click menu, the day buttons become **Previous race**, **Latest
  race** and **Next race**.
- Results are published shortly after each race. The ticker checks every 5 minutes.

### Live races

While a Grand Prix or sprint is running, the F1 ticker switches to a live view:
**LIVE**, the race, the lap, and any safety car, VSC or flag. Then every driver
in their current position with the **split to the car ahead** (PIT and OUT are
marked). Click it for the **Live race** tab, which shows the interval, gap to
the leader, laps and pit stops for every car, updating every 2 seconds. The
live view starts 10 minutes before lights out and switches back to the final
results once they're published.

There are two sources for the live data:

- **Free, no setup:** the live running order from ESPN. When ESPN's feed
  includes gaps, the splits between cars are worked out from them.
- **Exact gaps with your F1 account:** right-click → **F1 live timing
  sign-in…** connects to F1's official live timing, the same data the official
  F1 app uses. The window walks you through copying your sign-in from
  formula1.com. It lasts a few days at a time; when it runs out, the ticker
  tells you and falls back to ESPN until you sign in again. The sign-in is
  stored only on your PC.

## The game stats window

- **Header:** both teams' logos, names and records (shots on goal for NHL),
  the score, game status, start time, venue and TV. After a game ends, two red
  **▶ highlights** buttons appear, one per team.
- **Game summary tab:**
  - *NHL:* goals by period, three stars, team stats, every goal with assists,
    and every penalty.
  - *NFL:* points by quarter, team stats (yards, first downs, turnovers,
    possession...), and every scoring play.
  - *MLB:* runs by inning plus R/H/E, team batting and pitching numbers, and
    every scoring play.
  - *NBA:* points by quarter, team stats (FG%, 3P%, rebounds, assists...), and
    each team's leaders.
  - *Bundesliga:* goals by half, team stats (possession, shots, corners,
    fouls, cards), and key events: goals, cards and substitutions.
- **One tab per team, with every player's box score:**
  - *NHL:* skaters and goalies.
  - *NFL:* passing, rushing, receiving, defense, kicking and the rest.
  - *MLB:* batting and pitching.
  - *NBA:* minutes, shooting, rebounds, assists, +/-, points.
  - *Bundesliga:* starting XI and substitutes, with goals, assists, shots,
    fouls and cards.

  Click any column header to sort.
- **Standings tab:** the full league standings, with the two teams in the game
  highlighted in gold and their division/conference shown first.
  - *NHL:* by division: GP, W, L, OTL, points, point %, regulation wins,
    goals for/against, differential, last 10, streak.
  - *NFL:* by division: W, L, T, win %, points for/against, differential, streak.
  - *MLB:* by division: W, L, win %, games behind, runs scored/allowed,
    differential, streak.
  - *NBA:* by conference: W, L, win %, games behind, points per game for and
    against, differential, streak.
  - *Bundesliga:* the league table: played, W, D, L, goals for/against, goal
    difference, points.

  Standings are fetched once and reused for 10 minutes across stats windows.

Live games update every 20 seconds while the window is open. Press `Esc` to close it.

## Notes

- **Data:** NHL scores come from the NHL's own public feed (`api-web.nhle.com`).
  NFL, MLB, NBA and Bundesliga scores and stats come from ESPN's public feed
  (`site.api.espn.com`), and all team and league logos come from ESPN's image
  server. F1 results, qualifying and standings come from the Jolpica F1 API
  (`api.jolpi.ca`), the community-run successor to Ergast. Live F1 race order
  comes from ESPN, or from F1's official live timing
  (`livetiming.formula1.com`) when you sign in. None of these feeds
  needs a key, but none is officially documented, so any of them could change
  without notice. If a section ever shows blank, the feed
  has probably changed shape; the rest of the app keeps working. If a logo
  can't be downloaded, the ticker shows a team-colored square instead.
- **Nothing hidden behind the ticker:** at the top or bottom of the screen, the
  ticker registers with Windows as a reserved screen edge (like the taskbar),
  so maximized and snapped windows fit around it. When a full-screen app takes
  over (a full-screen video or game), the ticker steps behind it and comes back
  when you leave full screen. To let it float over windows instead, untick
  **"Keep windows from going under the ticker"** in the right-click menu.
- **How the highlight buttons work:** the first time you click one for a team,
  the app looks up that team's official YouTube channel and remembers it. It
  then checks the channel's latest uploads for a video posted after the game
  started with "highlights" or "recap" in the title, preferring one that names
  the opponent, and opens it in your browser with autoplay on. If the team
  hasn't posted it, it tries the league's official channel (NHL, NFL, MLB, NBA
  or Bundesliga). If neither has the video yet (it usually takes an hour or two
  after the game), it opens a YouTube search for the game instead and tells you so.
- Settings (league, position, speed, direction, scroll, always-on-top, and the
  team channels it has looked up) are saved in `%APPDATA%\SportsTicker\`,
  along with downloaded logos.
