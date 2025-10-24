#! /usr/bin/env python3

import argparse
import curses
import functools
import hashlib
import random
import re
import requests
import time
import webbrowser

from dataclasses import dataclass
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
)

Acks = Dict[str, Dict[str, str]]


@dataclass
class PrInfo:
    repo: Tuple[str, int]
    number: int
    title: str
    labels: List[str]
    assignees: List[str]
    author: str
    acks: Acks
    draft: bool
    needs_rebase: bool
    url: str
    rfm: Optional[bool]


@dataclass
class Filter:
    regex: str = ".*"
    apply: str = "p"
    regular: bool = True
    draft: bool = True
    needs_rebase: bool = True
    rfm: bool = False

    def clear_text_filter(self) -> None:
        self.regex = ".*"
        self.apply = "p"

    def clear_type_filter(self) -> None:
        self.regular = True
        self.draft = True
        self.needs_rebase = True


headers = {
    "accept": "application/vnd.github.v3+json",
}

repos: List[Tuple[str, int]] = []

prs_query = """
query($prs_cursor: String, $repo_owner: String!, $repo_name: String!) {
  repository(name: $repo_name, owner: $repo_owner) {
    pullRequests(states: [OPEN], first: 50, after: $prs_cursor) {
      nodes {
        number
        isDraft
        headRefOid
        title
        url
        author {
            login
        }
        assignees(first: 10, after: "") {
          nodes {
            login
          }
        }
        timelineItems(last: 50, itemTypes: [ISSUE_COMMENT, PULL_REQUEST_REVIEW]) {
          nodes {
            ... on HeadRefForcePushedEvent {
              author: actor {
                login
              }
            }
            ... on IssueComment{
              author {
                login
              }
              body
            }
            ... on PullRequestReview{
              author {
                login
              }
              body
            }
          }
          pageInfo {
            endCursor
            hasNextPage
            hasPreviousPage
            startCursor
          }
        }
        labels(first: 100) {
          nodes {
            name
          }
        }
      }
      pageInfo {
        endCursor
        hasNextPage
        hasPreviousPage
        startCursor
      }
    }
  }
}
"""

comments_query = """
    query($comments_cursor: String, $pr_num: Int!, $repo_owner: String!, $repo_name: String!) {
      repository(name: $repo_name, owner: $repo_owner) {
        pullRequest(number: $pr_num) {
          timelineItems(last: 50, after: $comments_cursor, itemTypes: [ISSUE_COMMENT, PULL_REQUEST_REVIEW]) {
            nodes {
              ... on HeadRefForcePushedEvent {
                author: actor {
                  login
                }
              }
              ... on IssueComment{
                author {
                  login
                }
                body
              }
              ... on PullRequestReview{
                author {
                  login
                }
                body
              }
            }
            pageInfo {
              endCursor
              hasNextPage
              hasPreviousPage
              startCursor
            }
          }
        }
      }
    }
"""

ACK_PATTERNS = [
    (re.compile(r"\b(NACK)\b"), "NACKs"),
    (re.compile(r"(ACK)(?:.*?)([0-9a-f]{6,40})\b"), "ACKs"),
    (re.compile(r"(ACK)\b"), "Concept ACKs"),
]


def extract_acks(user: str, text: str, acks: Acks, head_abbrev: str) -> None:
    for line in text.splitlines():
        if line.startswith(">") or line.startswith("~"):
            continue
        for pattern, ack_type in ACK_PATTERNS:
            match = pattern.search(line)
            if match:
                groups = match.groups()

                # Since we are processing in reverse, do not modify if the user has already left an ACK
                for _, existing_acks in acks.items():
                    if user in existing_acks:
                        return

                if len(groups) > 1 and groups[1][0:6] != head_abbrev:
                    acks["Stale ACKs"][user] = line
                else:
                    acks[ack_type][user] = line
                return


RFM_PATTERN = re.compile(r"\brfm\b")


def detect_rfm(text: str) -> bool:
    rfm = False
    for line in text.splitlines():
        if line.startswith(">") or line.startswith("~"):
            continue
        rfm |= bool(RFM_PATTERN.search(line.lower()))
    return rfm


def graphql_request(query: str, variables: Dict[str, str]) -> Any:
    while True:
        res = requests.post(
            "https://api.github.com/graphql",
            json={"query": query, "variables": variables},
            headers=headers,
        )
        if res.ok:
            return res.json()
        if res.status_code == 502:
            # 502 is a server error, wait a bit and try again
            time.sleep(10)
            continue
        raise Exception(
            f"Result: {res}, Content: {res.content!r}, Headers: {res.headers}"
        )


def get_pr_infos(stdscr: curses.window) -> List[PrInfo]:
    pr_infos: List[PrInfo] = []

    for repo in repos:
        repo_owner, repo_name = repo[0].split("/", maxsplit=1)
        pr_query_vars: Dict[str, str] = {
            "repo_name": repo_name,
            "repo_owner": repo_owner,
        }
        while True:
            stdscr.clear()
            stdscr.addstr(
                f"Fetching PRs from GitHub, this may take a while... ({len(pr_infos)} PRs loaded)"
            )
            stdscr.refresh()

            pr_query_res = graphql_request(prs_query, pr_query_vars)
            pr_list = pr_query_res["data"]["repository"]["pullRequests"]["nodes"]
            pr_page_info = pr_query_res["data"]["repository"]["pullRequests"][
                "pageInfo"
            ]

            for pr in pr_list:
                acks: Dict[str, Dict[str, str]] = {
                    "ACKs": {},
                    "Stale ACKs": {},
                    "NACKs": {},
                    "Approach ACKs": {},
                    "Concept ACKs": {},
                    "Other ACKs": {},
                }
                number = pr["number"]
                head_commit = pr["headRefOid"]
                head_abbrev = head_commit[0:6]
                author = pr["author"]["login"]
                rfm: Optional[bool] = False

                # Process comments and reviews, paginating as needed
                comments = pr["timelineItems"]["nodes"]
                comments_page_info = pr["timelineItems"]["pageInfo"]
                while True:
                    for comment in reversed(comments):
                        if "body" not in comment:
                            if rfm is False:
                                rfm = None
                            continue
                        if rfm is not None:
                            rfm |= detect_rfm(comment["body"])
                        if (
                            comment["author"] is None
                            or comment["author"]["login"] == "DrahtBot"
                            or comment["author"]["login"] == author
                        ):
                            continue
                        extract_acks(
                            comment["author"]["login"],
                            comment["body"],
                            acks,
                            head_abbrev,
                        )

                    if not comments_page_info["hasPreviousPage"]:
                        break

                    comments_query_vars = {
                        "comments_cursor": comments_page_info["startCursor"],
                        "pr_num": number,
                        "repo_name": repo_name,
                        "repo_owner": repo_owner,
                    }
                    comments_query_res = graphql_request(
                        comments_query, comments_query_vars
                    )
                    comments = comments_query_res["data"]["repository"]["pullRequest"][
                        "timelineItems"
                    ]["nodes"]
                    comments_page_info = comments_query_res["data"]["repository"][
                        "pullRequest"
                    ]["timelineItems"]["pageInfo"]

                labels = [n["name"] for n in pr["labels"]["nodes"]]
                assignees = [n["login"] for n in pr["assignees"]["nodes"]]
                pr_infos.append(
                    PrInfo(
                        repo=repo,
                        number=number,
                        title=pr["title"],
                        labels=labels,
                        assignees=assignees,
                        author=author,
                        acks=acks,
                        draft=pr["isDraft"],
                        needs_rebase="Needs rebase" in labels,
                        url=pr["url"],
                        rfm=rfm,
                    )
                )

            pr_query_vars["prs_cursor"] = pr_page_info["endCursor"]
            if not pr_page_info["hasNextPage"]:
                break
    return pr_infos


# Key function. Returns tuple containing (num acks, num stale acks, num nacks, num approch acks, num concept acks, num other acks)
def ack_key_func(primary_sort_key: str, info: PrInfo) -> Tuple[int, int, int, int]:
    acks = info.acks
    order = [
        "ACKs",
        "Stale ACKs",
        "NACKs",
        "Concept ACKs",
    ]
    order.insert(0, order.pop(order.index(primary_sort_key)))
    return (
        len(acks[order[0]]),
        len(acks[order[1]]),
        len(acks[order[2]]),
        len(acks[order[3]]),
    )


def str_to_width(
    item: str,
    width: int,
    padding: int = 3,
    ellipsis: str = "…",
    elide_middle: bool = False,
) -> str:
    actual_width = width - padding - len(ellipsis)
    item_str = f"{item:<{actual_width}}"
    if len(item_str) > actual_width:
        if elide_middle:
            item_str = f"{item_str[:3]}{ellipsis}{item_str[-(actual_width-3):]}"
        else:
            item_str = f"{item_str[:actual_width]}{ellipsis}"
    return f"{item_str:{width}}"


def detailed_pr_info(pad: curses.window, pr_info: PrInfo) -> None:
    lines, cols = pad.getmaxyx()
    lines -= 2
    cols -= 2

    text_lines = []

    if pr_info.draft:
        text_lines.append("Draft PR")

    text_lines.append(f"Number: {pr_info.number}")
    text_lines.append(f"Title: {pr_info.title}")
    text_lines.append(f"Author: {pr_info.author}")
    text_lines.append(f"Labels: {', '.join(pr_info.labels)}")
    text_lines.append(f"Assignees: {', '.join(pr_info.assignees)}")

    for ack_type, acks in pr_info.acks.items():
        text_lines.append(f"{ack_type}: {len(acks)}")
        for acker, ack in acks.items():
            text_lines.append(f"  {acker}: {ack}")

    max_width = max([len(line) for line in text_lines])
    shift = 0
    show_top = 0

    while True:
        pad.clear()
        for i in range(lines):
            if show_top + i >= len(text_lines):
                break
            pad.addstr(i + 1, 1, text_lines[show_top + i][shift : shift + cols])

        pad.box()
        pad.refresh()

        key = pad.getch()
        if key == ord("q"):
            pad.clear()
            pad.refresh()
            return
        elif key in [ord("j"), curses.KEY_DOWN]:
            show_top = min(show_top + 1, max(len(text_lines) - lines, 0))
        elif key in [ord("k"), curses.KEY_UP]:
            show_top = max(show_top - 1, 0)
        elif key in [ord("h"), curses.KEY_LEFT]:
            shift = max(shift - 1, 0)
        elif key in [ord("l"), curses.KEY_RIGHT]:
            shift = min(shift + 1, max_width - cols)
        elif key == curses.KEY_NPAGE:
            show_top = min(show_top + lines, max(len(text_lines) - lines, 0))
        elif key == curses.KEY_PPAGE:
            show_top = max(show_top - lines, 0)
        elif key == ord("g"):
            show_top = 0
        elif key == ord("G"):
            show_top = max(len(text_lines) - lines, 0)
        elif key == ord("o"):
            webbrowser.open(pr_info.url)


def apply_filter(sorted_pr_infos: List[PrInfo], pr_filter: Filter) -> List[PrInfo]:
    reg = re.compile(pr_filter.regex.lower())
    out = []
    for pr_info in sorted_pr_infos:
        if not pr_filter.draft and pr_info.draft:
            continue
        elif not pr_filter.needs_rebase and pr_info.needs_rebase:
            continue
        elif not pr_filter.regular:
            continue
        elif pr_filter.rfm and not pr_info.rfm:
            continue

        to_search = []
        if pr_filter.apply == "p":
            to_search.append(str(pr_info.number))
        elif pr_filter.apply == "t":
            to_search.append(pr_info.title)
        elif pr_filter.apply == "o":
            to_search.append(pr_info.author)
        elif pr_filter.apply == "l":
            to_search.extend(pr_info.labels)
        elif pr_filter.apply == "a":
            to_search.extend(pr_info.acks["ACKs"].keys())
        elif pr_filter.apply == "s":
            to_search.extend(pr_info.acks["Stale ACKs"].keys())
        elif pr_filter.apply == "n":
            to_search.extend(pr_info.acks["NACKs"].keys())
        elif pr_filter.apply == "c":
            to_search.extend(pr_info.acks["Concept ACKs"].keys())

        for s in to_search:
            match = reg.search(s.lower())
            if match:
                out.append(pr_info)
                break

    return out


def add_pr_str(
    stdscr: curses.window,
    line_pos: int,
    pr_num_str: str,
    repo_color: int,
    info_str: str,
    info_color: int,
    standout: bool,
) -> None:
    attrs = 0
    if standout:
        attrs |= curses.A_STANDOUT
    stdscr.addstr(line_pos, 0, pr_num_str, attrs | repo_color)
    stdscr.addstr(line_pos, len(pr_num_str), info_str, attrs | info_color)


def main(stdscr: curses.window) -> None:
    for i, (repo, _) in enumerate(repos):
        hashed_repo = int.from_bytes(hashlib.sha256(repo.encode()).digest()[:4])
        r = (hashed_repo & 0x3FF) % 1000
        g = (hashed_repo & 0x1FFC00) % 1000
        b = (hashed_repo & 0x7FF00000) % 1000
        curses.init_color(i + 20, r, g, b)
        curses.init_pair(i + 20, i + 20, curses.COLOR_BLACK)
        repos[i] = (repo, i + 20)

    pr_infos = get_pr_infos(stdscr)
    sort_key = "ACKs"
    pr_filter = Filter()
    sorted_pr_infos = sorted(
        pr_infos, key=functools.partial(ack_key_func, sort_key), reverse=True
    )

    stdscr.clear()
    lines, cols = stdscr.getmaxyx()
    show_range = lines - 2
    show_top = 0
    cursor_pos = 1

    curses.init_pair(1, curses.COLOR_BLUE, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_CYAN, curses.COLOR_BLACK)

    while True:
        pr_num_cols = int(cols * 0.07)
        title_cols = int(cols * 0.2)
        author_cols = int(cols * 0.05)
        assignees_cols = int(cols * 0.05)
        rfm_cols = int(cols * 0.03)
        labels_cols = int(cols * 0.1)
        acks_cols = int(cols * 0.15)
        stale_acks_cols = int(cols * 0.15)
        nacks_cols = int(cols * 0.1)
        concept_acks_cols = int(cols * 0.1)

        allocated_cols = (
            pr_num_cols
            + title_cols
            + author_cols
            + assignees_cols
            + rfm_cols
            + labels_cols
            + acks_cols
            + stale_acks_cols
            + nacks_cols
            + concept_acks_cols
        )
        concept_acks_cols += cols - allocated_cols

        pr_num_header = str_to_width("PR", pr_num_cols)
        title_header = str_to_width("Title", title_cols)
        author_header = str_to_width("Author", author_cols)
        labels_header = str_to_width("Labels", labels_cols)
        assignees_header = str_to_width("Assignees", assignees_cols)
        rfm_header = str_to_width("RFM?", rfm_cols)
        acks_header = str_to_width("ACKs", acks_cols)
        nacks_header = str_to_width("NACKs", nacks_cols)
        stale_header = str_to_width("Stale Acks", stale_acks_cols)
        concept_header = str_to_width("Concept", concept_acks_cols)

        stdscr.addstr(
            0,
            0,
            f"{pr_num_header}{title_header}{author_header}{assignees_header}{rfm_header}{labels_header}{acks_header}{nacks_header}{stale_header}{concept_header}",
            curses.A_BOLD,
        )

        num_items = len(sorted_pr_infos)
        for i in range(show_range):
            pr_i = show_top + i
            line_pos = 1 + i
            if pr_i >= len(sorted_pr_infos):
                break

            pr_info = sorted_pr_infos[pr_i]

            standout = line_pos == cursor_pos
            info_color = 0
            if pr_info.draft:
                info_color |= curses.color_pair(1)
            elif pr_info.needs_rebase:
                info_color |= curses.color_pair(2)

            pr_num_str = str_to_width(
                f"{pr_info.repo[0]}#{pr_info.number}",
                pr_num_cols,
                elide_middle=True,
            )
            title_str = str_to_width(pr_info.title, title_cols)
            author_str = str_to_width(pr_info.author, author_cols)
            labels_str = str_to_width(", ".join(pr_info.labels), labels_cols)
            assignees_str = str_to_width(", ".join(pr_info.assignees), assignees_cols)
            rfm_str = str_to_width("X" if pr_info.rfm else "", rfm_cols)
            acks_str = str_to_width(
                f"({len(pr_info.acks['ACKs'])}) "
                + ", ".join(pr_info.acks["ACKs"].keys()),
                acks_cols,
            )
            nacks_str = str_to_width(
                f"({len(pr_info.acks['NACKs'])}) "
                + ", ".join(pr_info.acks["NACKs"].keys()),
                nacks_cols,
            )
            stale_str = str_to_width(
                f"({len(pr_info.acks['Stale ACKs'])}) "
                + ", ".join(pr_info.acks["Stale ACKs"].keys()),
                stale_acks_cols,
            )
            concept_str = str_to_width(
                f"({len(pr_info.acks['Concept ACKs'])}) "
                + ", ".join(pr_info.acks["Concept ACKs"].keys()),
                concept_acks_cols,
            )

            add_pr_str(
                stdscr,
                line_pos,
                pr_num_str,
                curses.color_pair(pr_info.repo[1]),
                f"{title_str}{author_str}{assignees_str}{rfm_str}{labels_str}{acks_str}{nacks_str}{stale_str}{concept_str}",
                info_color,
                standout,
            )

        stdscr.move(lines - 1, 0)
        stdscr.refresh()

        key = stdscr.getch()
        if key in [ord("j"), curses.KEY_DOWN]:
            if cursor_pos == lines - 2:
                show_top = min(show_top + 1, max(num_items - show_range, 0))
            cursor_pos = min(cursor_pos + 1, lines - 2, num_items)
        elif key in [ord("k"), curses.KEY_UP]:
            if cursor_pos == 1:
                show_top = max(show_top - 1, 0)
            cursor_pos = max(cursor_pos - 1, 1)
        elif key == curses.KEY_NPAGE:
            show_top = min(show_top + show_range, max(num_items - show_range, 0))
        elif key == curses.KEY_PPAGE:
            show_top = max(show_top - show_range, 0)
        elif key == ord("g"):
            cursor_pos = 1
            show_top = 0
        elif key == ord("G"):
            cursor_pos = lines - 2
            show_top = max(num_items - show_range, 0)
        elif key == curses.KEY_RESIZE:
            lines, cols = stdscr.getmaxyx()
            show_range = lines - 2
            show_top = min(show_top, max(num_items - show_range, 0))
            cursor_pos = min(cursor_pos, lines - 2)

            stdscr.erase()
        elif key == ord("d"):
            pad = stdscr.subpad(20, 120, 15, 20)
            pr_idx = cursor_pos - 1 + show_top
            pr_info = sorted_pr_infos[pr_idx]
            detailed_pr_info(pad, pr_info)
        elif key == ord("o"):
            pr_idx = cursor_pos - 1 + show_top
            pr_info = sorted_pr_infos[pr_idx]
            webbrowser.open(pr_info.url)
        elif key == ord(":"):
            stdscr.move(lines - 1, 0)
            stdscr.addch(chr(key))
            curses.echo()
            cmd = stdscr.getstr().strip().decode()
            curses.noecho()
            stdscr.move(lines - 1, 0)
            stdscr.clrtoeol()
            if cmd == "q":
                break
            elif cmd == "r":
                pr_infos = get_pr_infos(stdscr)
                sorted_pr_infos = sorted(
                    pr_infos,
                    key=functools.partial(ack_key_func, sort_key),
                    reverse=True,
                )
                sorted_pr_infos = apply_filter(sorted_pr_infos, pr_filter)
            elif cmd == "sa":
                sort_key = "ACKs"
                sorted_pr_infos.sort(
                    key=functools.partial(ack_key_func, sort_key),
                    reverse=True,
                )
            elif cmd == "ss":
                sort_key = "Stale ACKs"
                sorted_pr_infos.sort(
                    key=functools.partial(ack_key_func, sort_key),
                    reverse=True,
                )
            elif cmd == "sn":
                sort_key = "NACKs"
                sorted_pr_infos.sort(
                    key=functools.partial(ack_key_func, sort_key),
                    reverse=True,
                )
            elif cmd == "sc":
                sort_key = "Concept ACKs"
                sorted_pr_infos.sort(
                    key=functools.partial(ack_key_func, sort_key),
                    reverse=True,
                )
            elif cmd == "sr":
                random.shuffle(sorted_pr_infos)
            elif cmd.startswith("f") and len(cmd) > 3 and cmd[2] == "/":
                pr_filter.apply = cmd[1]
                pr_filter.regex = cmd.split("/")[1]
                sorted_pr_infos = apply_filter(sorted_pr_infos, pr_filter)
                cursor_pos = 1
                show_top = 0
                stdscr.clear()
            elif cmd[0] == "c":
                if len(cmd) == 1:
                    pr_filter = Filter()
                elif cmd == "cf":
                    pr_filter.clear_text_filter()
                elif cmd == "chd":
                    pr_filter.draft = True
                elif cmd == "chr":
                    pr_filter.needs_rebase = True
                elif cmd == "ch":
                    pr_filter.clear_type_filter()
                elif cmd == "cm":
                    pr_filter.rfm = False
                else:
                    continue

                sorted_pr_infos = sorted(
                    pr_infos,
                    key=functools.partial(ack_key_func, sort_key),
                    reverse=True,
                )
                sorted_pr_infos = apply_filter(sorted_pr_infos, pr_filter)

                cursor_pos = 1
                stdscr.clear()
            elif cmd[0] == "h":
                if cmd == "hd":
                    pr_filter.draft = False
                elif cmd == "hr":
                    pr_filter.needs_rebase = False
                else:
                    continue

                sorted_pr_infos = apply_filter(sorted_pr_infos, pr_filter)

                cursor_pos = 1
                show_top = 0
                stdscr.clear()
            elif cmd[0] == "m":
                pr_filter.rfm = True
                sorted_pr_infos = apply_filter(sorted_pr_infos, pr_filter)
                cursor_pos = 1
                show_top = 0
                stdscr.clear()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "token_file", help="Path to the file containing the GitHub token"
    )
    parser.add_argument(
        "repos",
        nargs="+",
        help="Repositories to get PRs for specified as <owner>/<name>",
    )
    args = parser.parse_args()

    if "/" not in args.repos[0]:
        raise Exception(
            "The command line for ackboard has changed!! Repositories are now specified as single arguments of <owner>/<name>, and multiple repos can be specified. Please check --help for more information"
        )

    for repo in args.repos:
        repos.append((repo, 0))

    with open(args.token_file, "r") as f:
        line = f.readline().strip()
        if line.lower().startswith("bearer "):
            headers["Authorization"] = line
        else:
            headers["Authorization"] = "bearer " + line

    curses.wrapper(main)
