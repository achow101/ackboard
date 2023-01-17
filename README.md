# ACKBoard

A curses dashboard for ACKs.

## Github Token

ACKBoard requires a GitHub token in order to use the GraphQL API.
See the [GitHub Docs](https://docs.github.com/en/graphql/guides/forming-calls-with-graphql#authenticating-with-a-personal-access-token-classic) for how to get a token.
The token should be put in a text file whose path will be given as a CLI arg.

## Usage

### Command line arguments

```
usage: ackboard.py [-h] token_file repo_owner repo_name

positional arguments:
  token_file  Path to the file containing the GitHub token
  repo_owner  Repository owner
  repo_name   Repository name

options:
  -h, --help  show this help message and exit
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
| `b` | Open PR in browser |

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
| `b` | Open PR in browser |
