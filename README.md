# ACK Board

A curses dashboard for ACKs.

## Usage

### Command line arguments

```
usage: ackboard.py [-h] [-t TOKEN_FILE] repo_owner repo_name

positional arguments:
  repo_owner            Repository owner
  repo_name             Repository name

options:
  -h, --help            show this help message and exit
  -t TOKEN_FILE, --token-file TOKEN_FILE
                        Path to the file containing the GitHub token
```

### Main UI Keybinds

| Keys | Action |
|------|--------|
| `:q` | Quit |
| `j`, Down arrow | Move cursor down one line |
| `k`, Up arrow | Move cursor up one line |
| Page Down | Show next page of lines |
| Page Up | Show previous page of lines |
| `g` | Go to top |
| `G` | Go to bottom |
| `d` | Show details of the PR highlighted by the cursor |
| `:r` | Refresh data |
| `:sa` | Sort by number of ACKs |
| `:ss` | Sort by number of Stale ACKs |
| `:sn` | Sort by number of NACKs |
| `:sc` | Sort by number of Concept ACKs |
| `:f` | Apply a filter. See Filters for more info |
| `:c` | Clear filters |

#### Filters

A command to apply a filter begins with `:f`.
The next character indicates the column to apply the filter to. 
A `/` indicates the following string is the filter. 
The filter itself is a regular expression.

| Type Char | Column |
|-----------|--------|
| `p` | PR Number |
| `t` | PR Title |
| `o` | Original poster (PR Author) |
| `l` | Labels |
| `a` | ACKers and ACK comments |
| `s` | Stale ACKers and Stale ACK comments |
| `n` | NACKers and NACK comments |
| `c` | Concept ACKers and Concept ACK coments |

For example, the command `:fo/achow101` filters the listed PRs where the PR author name is `achow101`.

### Details UI Keybinds:

| Keys | Action |
|------|--------|
| `q` | Quit |
| `j`, Down arrow | Scroll down one line |
| `k`, Up arrow | Scroll up one line |
| `h`, Left arrow | Scroll left one character |
| `h`, Right arrow | Scroll right one character |
| Page Down | Show next page of lines |
| Page Up | Show previous page of lines |
| `g` | Go to top |
| `G` | Go to bottom |
