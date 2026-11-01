# Changelog

All notable changes to the Sports Ticker. Newest first.
Version numbers: **major.minor.patch**. A major bump means a big change in
what the app is, minor means new features, and patch means fixes and small tweaks.

## 2.5.0 — 2026-11-01
### Added
- **F1** as a sixth choice in the league drop-down (results from the Jolpica
  F1 API, the community successor to Ergast).
- F1 ticker: the latest race's name and date, then every finisher in order:
  position (gold, silver and bronze for the podium), team color, driver code,
  and gap to the winner or DNF. A purple dot marks the fastest lap. A **NEXT**
  chip shows the upcoming race and its start time in your time zone.
- F1 race window (click any F1 chip): winner and fastest lap, a **Race
  highlights** button (finds the race highlights on the official Formula 1
  YouTube channel), and tabs for race results (grid, positions gained, points,
  fastest laps), sprint (on sprint weekends), qualifying (Q1/Q2/Q3), driver
  standings, constructor standings and the weekend schedule.
- Clicking the NEXT race opens its weekend schedule (practice, sprint,
  qualifying, race) in your local time, plus the current standings.
- For F1, the right-click menu's day buttons become **Previous race**,
  **Latest race** and **Next race**.

## 2.4.0 — 2026-11-01
### Changed
- Every league now starts on **today's date** from your PC's calendar, both
  when the ticker opens and when you switch leagues.
- The NFL now shows only today's games, like the other leagues, instead of the
  whole week. On a day with no NFL games, it says "No NFL games today" and
  shows when the next game is.
- Moving back to today with Previous/Next day returns the ticker to following
  the calendar.
### Added
- The ticker rolls over to the new day on its own at midnight.
- Just after midnight (until 4 AM), games from the night before that are still
  in progress stay on the bar until they finish.

## 2.3.0 — 2026-11-01
### Added
- A version number. It shows at the bottom of the right-click menu.
- **What's new…** in the right-click menu opens this changelog inside the app.
- This CHANGELOG file. Every future update gets a new version number and an entry here.
- Downloads are now named with their version, e.g. `Sports_Ticker_v2.3.0.zip`.

## 2.2.0 — 2026-11-01
### Added
- A clear message when a league has nothing scheduled: "No NBA games today",
  "No NFL games this week", or "No MLB games on Sat Nov 7" for another day,
  with a calendar icon.
- When the feed lists upcoming dates, the bar also shows when the next games
  are, e.g. "Next games: Tue Nov 3".

## 2.1.0 — 2026-10-31
### Added
- **Standings** tab in every game's stats window, for all five leagues. The two
  teams in the game are highlighted in gold and their division or conference
  is listed first. Columns are sortable.

## 2.0.0 — 2026-10-31
### Added
- **NFL, MLB, NBA and Bundesliga**, alongside the NHL (scores and stats from
  ESPN's public feed).
- League drop-down: click the league logo at the left end of the bar to switch
  sports. The ticker remembers your choice.
- Team logos next to each team on the ticker and in the stats window; league
  logos in the badge and the drop-down. If a logo can't be downloaded, a
  team-colored square shows instead.
- Stats windows for each league: line score, team stats, scoring plays or key
  events (game leaders for the NBA), and every player's box score.
- Highlight buttons for every league, falling back to the league's own YouTube
  channel when the team hasn't posted the video yet.
### Changed
- Renamed from "NHL Ticker" to "Sports Ticker" (new folder, launcher and
  settings location). Settings from the NHL-only version don't carry over.

## 1.3.0 — 2026-10-31
### Added
- The ticker reserves its strip of the screen like the Windows taskbar, so
  maximized windows stop at its edge and nothing is hidden behind it. It steps
  behind full-screen apps such as full-screen video.
- Right-click option to turn this off and let the bar float over windows.
### Changed
- Highlight buttons now find the game's video on the team's official YouTube
  channel and open it with autoplay, instead of opening a YouTube search.

## 1.2.0 — 2026-10-31
### Added
- The launcher finds Python wherever it's installed, and offers to install it
  automatically if it's missing.
### Fixed
- The "Python was not found" error when Python wasn't on the PC's PATH.

## 1.1.1 — 2026-10-31
### Changed
- The YouTube highlight buttons appear only in the stats window, not on the ticker.

## 1.1.0 — 2026-10-31
### Added
- YouTube highlight buttons for finished games.
- A clear X close button at the right end of the bar.
- Option to scroll right to left (left to right is the default).
### Changed
- The bar is 1.5× thicker.
- The bar always scrolls left to right in a seamless loop, even when every game fits on screen.

## 1.0.0 — 2026-10-31
### Added
- First version: an always-on-top NHL score bar for Windows that scrolls all
  of today's games, with a stats window for each game (line score, team stats,
  scoring summary, penalties, three stars, skater and goalie stats).
