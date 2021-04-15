#!/usr/bin/env python
# -*- coding: utf-8 -*-

import copy
import json

import discord
from discord.ext import commands

from tournament_base import BaseTournament, is_tournament_host
from utils import format_date


class TournamentInfo(BaseTournament):
    """Class providing a tournament-info bot command."""

    is_host = commands.check(is_tournament_host)

    @commands.command(name='tournament-info', aliases=['ti'])
    #@commands.dm_only()  # Prevent public channel spam and make sure TO can't accidentally leak current round results
    async def tournament_info(self, ctx, *, round_or_puzzle_name=None):
        """Info on the tournament or specified round/puzzle.

        round_or_puzzle_name: (Case-insensitive) Return links to the matching
                              puzzle's announcement (/ results if available) posts.
                              If not specified, show all puzzle announcement links
                              and current tournament standings.
        """
        is_host = is_tournament_host(ctx)
        tournament_dir, tournament_metadata = self.get_active_tournament_dir_and_metadata(is_host=is_host)

        if round_or_puzzle_name is None:
            # Set up an embed listing all the rounds and their announcement messages
            embed = discord.Embed(title=tournament_metadata['name'], description="")

            if 'start_post' in tournament_metadata:
                embed.description += f"[Announcement]({tournament_metadata['start_post']})"

            embed.description += "\n**Rounds**:"
            for puzzle_name, round_metadata in tournament_metadata['rounds'].items():
                if 'start_post' in round_metadata:
                    embed.description += f"\n{round_metadata['round_name']}, {puzzle_name}:" \
                                         + f" [Announcement]({round_metadata['start_post']})"
                    if 'end_post' in round_metadata:
                        embed.description += f" | [Results]({round_metadata['end_post']})"
                elif is_host:
                    # Allow the TO to see schedule info on upcoming puzzles
                    embed.description += f"\n{round_metadata['round_name']}, {puzzle_name}:" \
                                         + f" Start: {format_date(round_metadata['start'])}" \
                                         + f" | End: {format_date(round_metadata['end'])}"

            await ctx.send(embed=embed)

            if 'start_post' in tournament_metadata:
                # Create a standings table (in chunks under discord's char limit as needed)
                for standings_msg in self.table_msgs(title_line="**Standings**",
                                                     table_text=self.standings_str(tournament_dir)):
                    await ctx.send(standings_msg)
            else:
                # Preview the tournament announcement post
                await ctx.send(f"On {format_date(tournament_metadata['start'])} the following announcement will be sent:")
                for msg_string in self.tournament_announcement(tournament_dir, tournament_metadata):
                    await ctx.send(msg_string)

            return

        # Convert to puzzle name
        puzzle_name = self.get_puzzle_name(tournament_metadata, round_or_puzzle_name, is_host=is_host, missing_ok=False)
        round_metadata = tournament_metadata['rounds'][puzzle_name]

        if is_host and 'start_post' not in round_metadata:
            # If this is the host checking an unannounced puzzle, simply preview the announcement post for them
            await ctx.send(f"On {format_date(round_metadata['start'])} the following announcement will be sent:")
            embed, attachment = self.round_announcement(tournament_dir, tournament_metadata, puzzle_name)
            await ctx.send(embed=embed, file=attachment)
            return

        embed = discord.Embed(title=f"{round_metadata['round_name']}, {puzzle_name}",
                              description=f"[Announcement]({round_metadata['start_post']})")

        # Prevent non-TO users from accessing rounds that haven't ended or that the bot hasn't announced the results of yet
        if 'end_post' in round_metadata:
            embed.description += f" | [Results]({round_metadata['end_post']})"

        await ctx.send(embed=embed)

        # If this is the TO, preview the results post for them (in separate msgs so the embed goes on top)
        if is_host and not 'end_post' in round_metadata:
            await ctx.send(f"On {format_date(round_metadata['end'])} the following announcement will be sent:")

            # Send each of the sub-2000 char announcement messages, adding the attachments to the last one
            msg_strings, attachments, _ = self.round_results_announcement_and_standings_change(tournament_dir, tournament_metadata, puzzle_name)
            for i, msg_string in enumerate(msg_strings):
                if i < len(msg_strings) - 1:
                    await ctx.send(msg_string)
                else:
                    await ctx.send(msg_string, files=attachments)

    @commands.command(name='tournament-standings-preview', aliases=['tsp', 'tournament-preview-standings', 'tps'])
    @is_host
    #@commands.dm_only()  # Make sure TO can't accidentally leak this
    async def standings_preview(self, ctx):
        """[TO-only] Preview the standings if all open rounds were tallied right now."""
        tournament_dir, tournament_metadata = self.get_active_tournament_dir_and_metadata(is_host=True)

        with open(tournament_dir / 'standings.json', 'r', encoding='utf-8') as f:
            standings = json.load(f)

        name_to_discord_tags = self.nickname_to_discord_tags_dict(tournament_dir)  # Reverse lookup dict needed for updates

        # Tally the current results of each open puzzle and add them to the current standings
        for puzzle_name, round_metadata in tournament_metadata['rounds'].items():
            if 'start_post' in round_metadata and 'end_post' not in round_metadata:
                standings_delta = self.round_results_announcement_and_standings_change(tournament_dir,
                                                                                       tournament_metadata,
                                                                                       puzzle_name)[2]

                # Create a teams-aware version of the lookup dict based on the teams for this puzzle
                with open(tournament_dir / round_metadata['dir'] / 'teams.json') as f:
                    teams = json.load(f)
                round_name_to_tags_dict = copy.deepcopy(name_to_discord_tags)
                round_name_to_tags_dict.update(teams)

                self.update_standings_dict(standings, standings_delta, round_name_to_tags_dict)

        # Create a standings table (in chunks under discord's char limit as needed)
        for standings_msg in self.table_msgs(title_line="**Standings**",
                                             table_text=self.standings_dict_to_str(tournament_dir, standings)):
            await ctx.send(standings_msg)
