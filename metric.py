#!/usr/bin/env python
# -*- coding: utf-8 -*-

"Contains functions for parsing tournament metric equations."

import ast
import inspect
import math
import operator as op

from schem.waldo import InstructionType
from schem.components import Reactor

# Operators allowed in puzzle metric strings
METRIC_OPS = {ast.Pow: op.pow, ast.USub: op.neg, ast.Mult: op.mul, ast.Div: op.truediv, ast.Add: op.add, ast.Sub: op.sub,
              # Built-in functions must be wrapped since otherwise they don't provide arg-count inspection info
              'log': lambda x: math.log(x, 10), 'max': lambda *x: max(*x), 'min': lambda *x: min(*x)}
# Functions for calculating values in a metric equation, given a Solution object
METRIC_VAR_TO_FN = {'cycles': lambda soln: soln.expected_score.cycles,
                    'reactors': lambda soln: soln.expected_score.reactors,
                    'symbols': lambda soln: soln.expected_score.symbols,
                    'waldos': lambda soln: waldos(soln),
                    'waldopath': lambda soln: waldopath(soln),
                    'bonders': lambda soln: used_bonders(soln),
                    'arrows': lambda soln: num_arrows(soln),
                    'flip_flops': lambda soln: num_instrs_of_type(soln, InstructionType.FLIP_FLOP),
                    'sensors': lambda soln: num_instrs_of_type(soln, InstructionType.SENSE),
                    'syncs': lambda soln: num_instrs_of_type(soln, InstructionType.SYNC)}
                    # TODO: 'outputs': lambda soln: completed_outputs(soln)
                    #       requires modifications to tournament validator to accept solutions without an expected
                    #       score if the metric contains 'outputs', and to eval the metric even if the solution crashes

def format_metric(metric_score, decimals=1):
    """12.123 -> 12.1, 12 -> 12, 12.0 -> 12.0"""
    s = str(metric_score)
    decimal_idx = s.find('.')
    return s[:decimal_idx + decimals + 1] if decimal_idx != -1 else s

def waldos(soln):
    """Return the number of waldos used by the solution (i.e. that have any non-Start instruction)."""
    return sum(1 for reactor in soln.reactors for waldo in reactor.waldos if waldo)

def waldopath(soln):
    """Return the total number of reactor cells that are covered by the path of either waldo. Note that this may
    include cells the waldo never actually enters due to how SC draws paths.
    Also includes the (at least one) cell occupied by an unused waldo, unlike some older tournament definitions.
    """
    def is_valid_posn(posn):
        return 0 <= posn.col < Reactor.NUM_COLS and 0 <= posn.row < Reactor.NUM_ROWS

    total_waldopath = 0
    branching_instr_types = set((InstructionType.SENSE, InstructionType.FLIP_FLOP))
    for reactor in soln.reactors:
        covered_posns = set()
        for waldo in reactor.waldos:
            # Note that this hasn't accounted for any arrow on the start posn yet
            start_posn, start_dirn = next((posn, cmd.direction) for posn, (_, cmd) in waldo.instr_map.items()
                                          if cmd.type == InstructionType.START)
            visited_posn_dirns = set()  # posn + direction tuples to catch when we're looping
            unexplored_branches_stack = [(start_posn, start_dirn)]
            while unexplored_branches_stack:
                cur_posn, cur_dirn = unexplored_branches_stack.pop()

                # Check the current cell for an arrow and/or branching instruction
                arrow_dirn, cmd = waldo.instr_map[cur_posn] if cur_posn in waldo.instr_map else (None, None)

                # Arrows update the direction of the current branch but don't create a new one
                if arrow_dirn is not None:
                    cur_dirn = arrow_dirn

                # Check the current position/direction against the visit map. We do this after evaluating the arrow to
                # reduce excess visits (since the original direction of a waldo never matters to its future path if an
                # arrow is present, unlike with branching commands)
                posn_dirn = (cur_posn, cur_dirn)
                if posn_dirn in visited_posn_dirns:
                    # We've already explored this cell in the current direction and must have already added any branches
                    # starting from this cell, so end this branch
                    continue
                else:
                    visited_posn_dirns.add(posn_dirn)

                # Add any new branch
                if cmd is not None and cmd.type in branching_instr_types:
                    next_branch_posn = cur_posn + cmd.direction
                    if is_valid_posn(next_branch_posn):
                        unexplored_branches_stack.append((next_branch_posn, cmd.direction))

                # Put the current branch back on top of the stack
                next_posn = cur_posn + cur_dirn
                if is_valid_posn(next_posn):
                    unexplored_branches_stack.append((next_posn, cur_dirn))

            # Once we've explored all branches, add this waldo's visited posns to the reactor's covered posns
            covered_posns |= set(posn for posn, _ in visited_posn_dirns)

        # Add this reactor's number of covered posns to the total waldopath
        total_waldopath += len(covered_posns)

    return total_waldopath

def used_bonders(soln):
    """Return the number of bonders in the solution which have been placed adjacent to another (compatible) bonder."""
    num_used_bonders = 0
    for reactor in soln.reactors:
        # TODO: These weren't really meant to be user-exposed, relying on them is a bit sus
        used_bonders = set(p1 for p1, _, _, in reactor.bond_plus_pairs)
        used_bonders |= set(p2 for _, p2, _, in reactor.bond_plus_pairs)
        used_bonders |= set(p1 for p1, _, _, in reactor.bond_minus_pairs)
        used_bonders |= set(p2 for _, p2, _, in reactor.bond_minus_pairs)
        num_used_bonders += len(used_bonders)

    return num_used_bonders

def num_arrows(soln):
    """Return the number of arrows in the solution."""
    return sum(1
               for reactor in soln.reactors
               for waldo in reactor.waldos
               for arrow, _ in waldo.instr_map.values()
               if arrow is not None)

def num_instrs_of_type(soln, instr_type):
    """Return the number of non-arrow instructions of the given type in the solution."""
    return sum(1
               for reactor in soln.reactors
               for waldo in reactor.waldos
               for _, cmd in waldo.instr_map.values()
               if cmd is not None and cmd.type == instr_type)

def completed_outputs(soln):
    """Given a Solution object that has run to completion or error, return the number of completed output molecules."""
    return sum(output.current_count for output in soln.outputs)

def ast_vars(node):
    """Return a set of all variables in the given AST."""
    if isinstance(node, ast.Name):
        return set((node.id,))
    elif isinstance(node, ast.Num):
        return set()
    elif isinstance(node, ast.BinOp):
        return ast_vars(node.left) | ast_vars(node.right)
    elif isinstance(node, ast.UnaryOp):
        return ast_vars(node.operand)
    elif isinstance(node, ast.Call):
        return set().union(*(ast_vars(arg) for arg in node.args))
    else:
        raise TypeError(node)

def ast_operators(node):
    """Return a set of all operators and calls in the given AST, or return an error if any are invalid."""
    if isinstance(node, ast.Name) or isinstance(node, ast.Num):
        return set()
    elif isinstance(node, ast.BinOp):
        return set((type(node.op),)) | ast_operators(node.left) | ast_operators(node.right)
    elif isinstance(node, ast.UnaryOp):
        return set((type(node.op),)) | ast_operators(node.operand)
    elif isinstance(node, ast.Call):
        if node.func.id not in METRIC_OPS:
            raise ValueError(f"Unknown fn `{node.func.id}` in metric equation.")

        # Make sure the number of args matches the fn signature
        fn_argspec = inspect.getfullargspec(METRIC_OPS[node.func.id])
        if (not node.args or
                (fn_argspec.varargs is None and fn_argspec.varkw is None
                 and len(node.args) != len(fn_argspec.args))):
            raise ValueError(f"Unexpected number of args to {node.func.id}")

        return set((node.func.id,)).union(*(ast_operators(arg) for arg in node.args))
    else:
        raise TypeError(node)

def validate_metric(metric_str):
    """Raise an error if the given metric string is unparsable."""
    # Allow specifying powers as either ^ or **
    metric_str = metric_str.replace('^', '**')

    # Parse the string as AST
    metric_ast = ast.parse(metric_str, mode='eval').body

    for metric_op in ast_operators(metric_ast):
        if metric_op not in METRIC_OPS:
            raise ValueError(f"Unknown operator `{metric_op}` in metric equation.")

    for metric_var in ast_vars(metric_ast):
        if metric_var not in METRIC_VAR_TO_FN:
            raise ValueError(f"Unknown var `{metric_var}` in metric equation.")

def get_metric_and_terms(soln, metric_str):
    """Score the (assumed to be already-validated) given solution using the given metric expression. Respects python's
    usual order of operations (i.e. BEDMAS).
    Return the score along with a dict of the value for each term in the metric.
    Valid ops: +, -, *, /, ** or ^
    Valid terms: any real number, or any of:
        cycles, reactors, symbols: Per usual.
        waldos: Number of non-empty waldos in the solution.
        waldopath: Number of reactor cells crossed by a waldopath
    """
    # Allow specifying powers as either ^ or **
    metric_str = metric_str.replace('^', '**')

    # Parse the metric into an AST
    ast_tree = ast.parse(metric_str, mode='eval').body

    # Calculate all variables the metric needs. Sorted in same order as they appear in METRIC_VAR_TO_FN
    # (this is the order they'll appear as column in results announcements)
    used_vars = ast_vars(ast_tree)
    vars_dict = {var: METRIC_VAR_TO_FN[var](soln) for var in METRIC_VAR_TO_FN.keys() if var in used_vars}

    return eval_ast(ast_tree, vars_dict), vars_dict

def eval_metric(soln, metric_str):
    """Score the (assumed to be already-validated) given solution using the given metric expression. Respects python's
    usual order of operations (i.e. BEDMAS). Return the score.
    Valid ops: +, -, *, /, ** or ^
    Valid terms: any real number, or any of:
        cycles, reactors, symbols: Per usual.
        waldos: Number of non-empty waldos in the solution.
        waldopath: Number of reactor cells crossed by a waldopath
    """
    return get_metric_and_terms(soln, metric_str)[0]

def eval_ast(node, vars_dict):
    """Helper for evaluating a puzzle metric (safer than built-in eval)"""
    if isinstance(node, ast.Name):
        if node.id not in vars_dict:
            raise Exception(f"Unknown metric var `{node.id}`")
        return vars_dict[node.id]
    elif isinstance(node, ast.Num):
        return node.n
    elif isinstance(node, ast.BinOp):
        return METRIC_OPS[type(node.op)](eval_ast(node.left, vars_dict), eval_ast(node.right, vars_dict))
    elif isinstance(node, ast.UnaryOp):
        return METRIC_OPS[type(node.op)](eval_ast(node.operand, vars_dict))
    elif isinstance(node, ast.Call):
        return METRIC_OPS[node.func.id](*(eval_ast(arg, vars_dict) for arg in node.args))
    else:
        raise TypeError(node)
