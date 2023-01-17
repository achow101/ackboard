#! /usr/bin/env python3

import argparse
import curses
import functools
import re
import requests

from dataclasses import dataclass
from typing import (
    Dict,
    List,
    Tuple,
    Union,
)

Acks = Dict[str, Dict[str, str]]


@dataclass
class PrInfo:
    title: str
    labels: List[str]
    author: str
    acks: Acks
    draft: bool
    needs_rebase: bool


headers = {
    "accept": "application/vnd.github.v3+json",
}

repo_vars = {
    "repo_name": "",
    "repo_owner": "",
}


prs_query = """
query($prs_cursor: String, $repo_owner: String!, $repo_name: String!) {
  repository(name: $repo_name, owner: $repo_owner) {
    pullRequests(states: [OPEN], first: 100, after: $prs_cursor) {
      nodes {
        number
        isDraft
        headRefOid
        title
        author {
            login
        }
        comments(first: 100) {
          nodes {
            author {
              login
            }
            body
          }
          pageInfo {
            endCursor
            hasNextPage
            hasPreviousPage
            startCursor
          }
        }
        reviews(first: 100) {
          nodes {
            author {
              login
            }
            body
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
          comments(first: 100, after: $comments_cursor) {
            nodes {
              author {
                login
              }
              body
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

reviews_query = """
    query($reviews_cursor: String, $pr_num: Int!, $repo_owner: String!, $repo_name: String!) {
      repository(name: $repo_name, owner: $repo_owner) {
        pullRequest(number: $pr_num) {
          reviews(first: 100, after: $reviews_cursor) {
            nodes {
              author {
                login
              }
              body
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
                if len(groups) > 1 and groups[1][0:6] != head_abbrev:
                    acks["Stale ACKs"][user] = line
                else:
                    acks[ack_type][user] = line
                return


def get_pr_infos() -> Dict[int, PrInfo]:
    pr_infos: Dict[int, PrInfo] = {}
    pr_query_vars: Dict[str, str] = repo_vars.copy()
    while True:
        pr_res = requests.post(
            "https://api.github.com/graphql",
            json={"query": prs_query, "variables": pr_query_vars},
            headers=headers,
        )
        if not pr_res.ok:
            raise Exception(
                f"Result: {pr_res}, Content: {pr_res.content!r}, Headers: {pr_res.headers}"
            )
        pr_query_res = pr_res.json()
        pr_list = pr_query_res["data"]["repository"]["pullRequests"]["nodes"]
        pr_page_info = pr_query_res["data"]["repository"]["pullRequests"]["pageInfo"]

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

            # Process comments, paginating as needed
            comments = pr["comments"]["nodes"]
            comments_page_info = pr["comments"]["pageInfo"]
            while True:
                for comment in comments:
                    if (
                        comment["author"] is None
                        or comment["author"]["login"] == "DrahtBot"
                    ):
                        continue
                    extract_acks(
                        comment["author"]["login"], comment["body"], acks, head_abbrev
                    )

                if not comments_page_info["hasNextPage"]:
                    break

                comments_query_vars = {
                    "comments_cursor": comments_page_info["endCursor"],
                    "pr_num": number,
                }
                comments_query_vars.update(repo_vars)
                comments_res = requests.post(
                    "https://api.github.com/graphql",
                    json={"query": comments_query, "variables": comments_query_vars},
                    headers=headers,
                )
                if not comments_res.ok:
                    raise Exception(
                        f"Result: {comments_res}, Content: {comments_res.content!r}, Headers: {comments_res.headers}"
                    )
                comments_query_res = comments_res.json()
                comments = comments_query_res["data"]["repository"]["pullRequest"][
                    "comments"
                ]["nodes"]
                comments_page_info = comments_query_res["data"]["repository"][
                    "pullRequest"
                ]["comments"]["pageInfo"]

            # Process reviews, paginating as needed
            reviews = pr["reviews"]["nodes"]
            reviews_page_info = pr["reviews"]["pageInfo"]
            while True:
                for review in reviews:
                    if (
                        review["author"] is None
                        or review["author"]["login"] == "DrahtBot"
                    ):
                        continue
                    extract_acks(
                        review["author"]["login"], review["body"], acks, head_abbrev
                    )

                if not reviews_page_info["hasNextPage"]:
                    break

                reviews_query_vars = {
                    "reviews_cursor": reviews_page_info["endCursor"],
                    "pr_num": number,
                }
                reviews_query_vars.update(repo_vars)
                reviews_res = requests.post(
                    "https://api.github.com/graphql",
                    json={"query": reviews_query, "variables": reviews_query_vars},
                    headers=headers,
                )
                if not reviews_res.ok:
                    raise Exception(
                        f"Result: {reviews_res}, Content: {reviews_res.content!r}, Headers: {reviews_res.headers}"
                    )
                reviews_query_res = reviews_res.json()
                reviews = reviews_query_res["data"]["repository"]["pullRequest"][
                    "reviews"
                ]["nodes"]
                reviews_page_info = reviews_query_res["data"]["repository"][
                    "pullRequest"
                ]["reviews"]["pageInfo"]

            labels = [n["name"] for n in pr["labels"]["nodes"]]
            pr_infos[number] = PrInfo(
                title=pr["title"],
                labels=labels,
                author=pr["author"]["login"],
                acks=acks,
                draft=pr["isDraft"],
                needs_rebase="Needs rebase" in labels,
            )

        pr_query_vars["prs_cursor"] = pr_page_info["endCursor"]
        if not pr_page_info["hasNextPage"]:
            break
    return pr_infos


# Key function. Returns tuple containing (num acks, num stale acks, num nacks, num approch acks, num concept acks, num other acks)
def ack_key_func(
    primary_sort_key: str, pr_info_item: Tuple[int, PrInfo]
) -> Tuple[int, int, int, int]:
    _, info = pr_info_item
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


def str_to_width(item: str, width: int, padding: int = 4, ellipsis: str = "…") -> str:
    actual_width = width - padding - len(ellipsis)
    item_str = f"{item:<{actual_width}}"
    if len(item_str) > actual_width:
        item_str = f"{item_str[:actual_width]}{ellipsis}"
    return f"{item_str:{width}}"


def detailed_pr_info(pad: curses.window, pr_num: int, pr_info: PrInfo) -> None:
    lines, cols = pad.getmaxyx()
    lines -= 2
    cols -= 2

    text_lines = []

    if pr_info.draft:
        text_lines.append("Draft PR")

    text_lines.append(f"Number: {pr_num}")
    text_lines.append(f"Title: {pr_info.title}")
    text_lines.append(f"Author: {pr_info.author}")
    text_lines.append(f"Labels: {', '.join(pr_info.labels)}")

    for ack_type, acks in pr_info.acks.items():
        text_lines.append(f"{ack_type}: {len(acks)}")
        for acker, ack in acks.items():
            text_lines.append(f"  {acker}: {ack}")

    max_width = max([len(l) for l in text_lines])
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


def apply_filter(
    sorted_pr_infos: List[Tuple[int, PrInfo]], filter_regex: str, apply_to: str
) -> List[Tuple[int, PrInfo]]:
    pr_filter = re.compile(filter_regex.lower())
    out = []
    for pr_num, pr_info in sorted_pr_infos:
        to_search = []
        if apply_to == "p":
            to_search.append(str(pr_num))
        elif apply_to == "t":
            to_search.append(pr_info.title)
        elif apply_to == "o":
            to_search.append(pr_info.author)
        elif apply_to == "l":
            to_search.extend(pr_info.labels)
        elif apply_to == "a":
            to_search.extend(pr_info.acks["ACKs"].keys())
        elif apply_to == "s":
            to_search.extend(pr_info.acks["Stale ACKs"].keys())
        elif apply_to == "n":
            to_search.extend(pr_info.acks["NACKs"].keys())
        elif apply_to == "c":
            to_search.extend(pr_info.acks["Concept ACKs"].keys())

        for s in to_search:
            match = pr_filter.search(s.lower())
            if match:
                out.append((pr_num, pr_info))
                break

    return out


def main(stdscr: curses.window) -> None:

    pr_infos = get_pr_infos()
    sort_key = "ACKs"
    sorted_pr_infos = sorted(
        pr_infos.items(), key=functools.partial(ack_key_func, sort_key), reverse=True
    )

    stdscr.clear()
    lines, cols = stdscr.getmaxyx()
    show_range = lines - 2
    show_top = 0
    cursor_pos = 1

    curses.init_pair(1, curses.COLOR_BLUE, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_CYAN, curses.COLOR_BLACK)

    while True:
        pr_num_cols = 10
        title_cols = int(cols * 0.2)
        labels_cols = int(cols * 0.1)
        author_cols = int(cols * 0.05)

        all_acks_cols = cols - pr_num_cols - title_cols - labels_cols - author_cols
        acks_cols = int(all_acks_cols * 0.3)
        stale_acks_cols = int(all_acks_cols * 0.3)
        nacks_cols = int(all_acks_cols * 0.2)
        concept_acks_cols = int(all_acks_cols * 0.2)

        pr_num_header = str_to_width("PR", pr_num_cols)
        title_header = str_to_width("Title", title_cols)
        author_header = str_to_width("Author", author_cols)
        labels_header = str_to_width("Labels", labels_cols)
        acks_header = str_to_width("ACKs", acks_cols)
        nacks_header = str_to_width("NACKs", nacks_cols)
        stale_header = str_to_width("Stale Acks", stale_acks_cols)
        concept_header = str_to_width("Concept", concept_acks_cols)

        stdscr.addstr(
            0,
            0,
            f"{pr_num_header}{title_header}{author_header}{labels_header}{acks_header}{nacks_header}{stale_header}{concept_header}",
            curses.A_BOLD,
        )

        num_items = len(sorted_pr_infos)
        for i in range(show_range):
            pr_i = show_top + i
            line_pos = 1 + i
            if pr_i >= len(sorted_pr_infos):
                break

            pr_num, pr_info = sorted_pr_infos[pr_i]

            attrs = 0
            if line_pos == cursor_pos:
                attrs |= curses.A_STANDOUT
            if pr_info.draft:
                attrs |= curses.color_pair(1)
            elif pr_info.needs_rebase:
                attrs |= curses.color_pair(2)

            pr_num_str = str_to_width(str(pr_num), pr_num_cols)
            title_str = str_to_width(pr_info.title, title_cols)
            author_str = str_to_width(pr_info.author, author_cols)
            labels_str = str_to_width(", ".join(pr_info.labels), labels_cols)
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

            stdscr.addstr(
                line_pos,
                0,
                f"{pr_num_str}{title_str}{author_str}{labels_str}{acks_str}{nacks_str}{stale_str}{concept_str}",
                attrs,
            )

        stdscr.move(cursor_pos, 0)
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
            pr_num, pr_info = sorted_pr_infos[pr_idx]
            detailed_pr_info(pad, pr_num, pr_info)
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
                stdscr.clear()
                stdscr.addstr(0, 0, "Refreshing")
                stdscr.move(0, 0)
                stdscr.refresh()

                pr_infos = get_pr_infos()
                sorted_pr_infos = sorted(
                    pr_infos.items(),
                    key=functools.partial(ack_key_func, sort_key),
                    reverse=True,
                )
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
            elif cmd.startswith("f") and len(cmd) > 3 and cmd[2] == "/":
                apply_to = cmd[1]
                filter_regex = cmd.split("/")[1]
                sorted_pr_infos = apply_filter(sorted_pr_infos, filter_regex, apply_to)
                cursor_pos = 1
                stdscr.move(1, 0)
                stdscr.clrtobot()
            elif cmd == "c":
                sorted_pr_infos = sorted(
                    pr_infos.items(),
                    key=functools.partial(ack_key_func, sort_key),
                    reverse=True,
                )
                cursor_pos = 1
                stdscr.move(1, 0)
                stdscr.clrtobot()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "token_file", help="Path to the file containing the GitHub token"
    )
    parser.add_argument("repo_owner", help="Repository owner")
    parser.add_argument("repo_name", help="Repository name")
    args = parser.parse_args()

    repo_vars["repo_owner"] = args.repo_owner
    repo_vars["repo_name"] = args.repo_name

    with open(args.token_file, "r") as f:
        line = f.readline().strip()
        headers["Authorization"] = line

    curses.wrapper(main)
