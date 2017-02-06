#!/usr/bin/env python
"""This module provides an interface to run Polly's SCoP detection either with
a custom sequence generated by a heuristic algorithm or with a fixed
preoptimization sequence.
"""
import sys
import getopt
import polly_stats
import genetic1_opt
import genetic2_opt
import hill_climber
import greedy
import toposort_sequences


__author__ = "Christoph Woller"
__credits__ = ["Christoph Woller"]
__maintainer__ = "Christoph Woller"
__email__ = "wollerch@fim.uni-passau.de"

# The preparation passes of Polly (-polly-canonicalize)
POLLY_CANONICALIZE_PASSES = ['-domtree', '-mem2reg', '-instcombine',
                             '-simplifycfg', '-tailcallelim', '-reassociate',
                             '-loops', '-loop-simplify', '-lcssa',
                             '-loop-rotate', '-scalar-evolution', '-iv-users',
                             '-polly-indvars', '-polly-prepare', '-notti',
                             '-targetlibinfo']

# Passes contained in O3 and not in the Polly preparation passes
# (-polly-canonicalize)
O3_PASSES = ['-adce', '-argpromotion', '-basicaa', '-constmerge',
             '-correlated-propagation', '-deadargelim', '-dse', '-early-cse',
             '-indvars', '-inline', '-ipsccp', '-licm', '-loop-deletion',
             '-tbaa', '-barrier', '-basiccg', '-block-freq', '-branch-prob',
             '-functionattrs', '-globaldce', '-globalopt', '-gvn',
             '-inline-cost', '-ipsccp', '-jump-threading', '-lazy-value-info',
             '-loop-unswitch', '-loop-idiom', '-loop-unroll',
             '-loop-vectorize', '-memcpyopt', '-memdep', '-no-aa', '-prune-eh',
             '-sccp', '-slp-vectorizer', '-sroa', '-strip-dead-prototypes']

# The passes that appear most frequently in custom sequences.
FREQUENT_PASSES = ['-inline', '-ipsccp', '-basicaa', '-polly-indvars', '-gvn',
                   '-instcombine', '-polly-prepare', '-simplifycfg',
                   '-globaldce', '-jump-threading', '-mem2reg', '-sroa',
                   '-globalopt', '-functionattrs', '-early-cse',
                   '-loop-unroll']

# Variant 1 of new fixed preoptimization sequence with -inline pass.
POLLY_PREOPT_INLINE = ['-mem2reg', '-early-cse', '-inline', '-functionattrs',
                       '-instcombine', '-globalopt', '-sroa', '-gvn',
                       '-ipsccp', '-basicaa', '-simplifycfg',
                       '-jump-threading', '-polly-indvars', '-loop-unroll',
                       '-globaldce', '-polly-prepare']

# Variant 2 of new fixed preoptimization sequence without -inline.
# This is the recommended variant.
POLLY_PREOPT = ['-mem2reg', '-early-cse', '-functionattrs', '-instcombine',
                '-globalopt', '-sroa', '-gvn', '-ipsccp', '-basicaa',
                '-simplifycfg', '-jump-threading', '-polly-indvars',
                '-loop-unroll', '-globaldce', '-polly-prepare']


def __run_scop_detection(program):
    """Runs Polly's SCoP detection for the specified program and prints out
    its results.

    Args:
        program (string): the name of the application for which the SCoP
            detection should run.
    """
    from benchbuild.settings import CFG
    sequence = CFG["sequence"].value()
    if sequence == 'genetic1':
        passes = O3_PASSES + POLLY_CANONICALIZE_PASSES
        opt_flags = genetic1_opt.generate_custom_sequence(program, passes,
                                                          False)
    elif sequence == 'genetic2':
        passes = O3_PASSES + POLLY_CANONICALIZE_PASSES
        opt_flags = genetic2_opt.generate_custom_sequence(program, passes,
                                                          False)
    elif sequence == 'hill_climber':
        passes = FREQUENT_PASSES
        opt_flags = hill_climber.generate_custom_sequence(program, passes,
                                                          debug=False)
    elif sequence == 'greedy':
        passes = FREQUENT_PASSES
        opt_flags = greedy.generate_custom_sequence(program, passes,
                                                    debug=False)
    elif sequence == 'no_preparation':
        opt_flags = []
    elif sequence == 'polly-canonicalize':
        opt_flags = ['-polly-canonicalize']
    elif sequence == 'toposort':
        opt_flags = toposort_sequences.generate_custom_sequence(program)
    elif sequence == 'polly-preopt-inline':
        opt_flags = POLLY_PREOPT_INLINE
    elif sequence == 'polly-preopt':
        opt_flags = POLLY_PREOPT
    else:
        opt_flags = ['-O3', '-polly-canonicalize']

    print('Sequence: ' + sequence)
    print('Optimization Passes: ' + str(opt_flags))
    print('')
    polly_stats.detect_scops(opt_flags, program)


def __usage():
    """Prints out the usage of this python script."""
    print('Wrong usage!\n'
          'Usage: run_scop_detection [-s sequence] program\n\n'
          'Possible sequences:\n'
          '\tgenetic1: uses a custom sequence generated by a genetic'
          ' algorithm for preoptimization\n'
          '\tgenetic2: uses a custom sequence generated by a genetic'
          ' algorithm for preoptimization\n'
          '\thill_climber: uses a custom sequence generated by a hill '
          'climber algorithm for preoptimization\n'
          '\tgreedy: uses a custom sequence generated by a greedy algorithm '
          'for preoptimization\n'
          '\ttoposort: uses a custom sequence generated from directed '
          'acyclic graph (DAG) with topological sorting for preoptimization\n'
          '\tno_preparation: calls just the SCoP detection\n'
          '\tpolly-canonicalize: uses -polly-canonicalize for '
          'preoptimization\n'
          '\tpolly-preopt: uses new fixed sequence variant 2 for '
          'preoptimization\n'
          '\tpolly-preopt-inline: uses new fixed sequence variant 1 for '
          'preoptimization\n\n'
          'If the -a flag is not used, opt is called with the flags -O3 and '
          '-polly-canonicalize before SCoP detection')


def main(argv):
    """Starts the SCoP detection."""
    try:
        opts, args = getopt.getopt(argv, 'hs:', ['help', 'sequence='])
    except getopt.GetoptError:
        __usage()
        sys.exit(2)

    for opt, _ in opts:
        if opt in ('-h', '--help'):
            __usage()
            sys.exit()
        elif opt in ('-s', '--sequence'):
            if args:
                __run_scop_detection(args[0])
            else:
                __usage()


if __name__ == '__main__':
    main(sys.argv[1:])
