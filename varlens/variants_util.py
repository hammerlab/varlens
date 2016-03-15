# Copyright (c) 2015. Mount Sinai School of Medicine
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import collections

import typechecks
import pandas
import varcode
import varcode.reference
import logging
from . import util

from . import evaluation, Locus

STANDARD_DATAFRAME_COLUMNS = [
    "genome",
    "contig",
    "interbase_start",
    "interbase_end",
    "ref",
    "alt",
]

def add_args(parser):
    parser.add_argument("--variants", nargs="+", default=[],
        help="Path to VCF file. Any number of VCF files may be specified.")
    parser.add_argument("--variant-filter",
        nargs="+", action="append", default=[])
    parser.add_argument("--variant-genome")
    parser.add_argument("--include-failing-variants",
        action="store_true", default=False)
    parser.add_argument("--variant-source-name", nargs="+")
    parser.add_argument("--max-variants-per-source", type=int)
    parser.add_argument("--single-variant", nargs=3, action="append",
        default=[], metavar=("LOCUS", "REF", "ALT"),
        help="Literal variant. Can be specified any number of times.")

def load_from_args_as_dataframe(args):
    '''
    Given parsed variant-loading arguments, return a pandas DataFrame.

    If no variant loading arguments are specified, return None.
    '''
    if not args.variants and not args.single_variant:
        return None

    if args.variant_source_name:
        variant_source_names = util.expand(
            args.variant_source_name,
            'variant_source_name',
            'variant source',
            len(args.variants))
    else:
        variant_source_names = util.drop_prefix(args.variants)

    variant_filters = zip(*[
        util.expand(
            value, 'variant_filter', 'variant source', len(args.variants))
        for value in args.variant_filter
    ])
    if not variant_filters:
        variant_filters = [[]] * len(args.variants)

    assert len(variant_filters) == len(args.variants)

    variant_to_sources = collections.defaultdict(list)

    dfs = []
    for i in range(len(args.variants)):
        name = variant_source_names[i]
        prefix = (
            'metadata:' if len(args.variants) == 1 else "metadata:%s:" % name)
        df = load_as_dataframe(
            args.variants[i],
            filters=variant_filters[i],
            name=name,
            genome=args.variant_genome,
            max_variants=args.max_variants_per_source,
            only_passing=not args.include_failing_variants,
            metadata_column_prefix=prefix)

        if df.shape[0] == 0:
            logging.warn("No variants loaded from: %s" % args.variants[i])
        else:
            for variant in df.variant:
                variant_to_sources[variant].append(name)
            dfs.append(df)

    if args.single_variant:
        variants = []
        extra_args = {}
        if args.variant_genome:
            extra_args = {
                'ensembl': varcode.reference.infer_genome(args.variant_genome)
            }
        for (locus_str, ref, alt) in args.single_variant:
            locus = Locus.parse(locus_str)
            variant = varcode.Variant(
                    locus.contig,
                    locus.inclusive_start,
                    ref,
                    alt,
                    **extra_args)
            variants.append(variant)
            variant_to_sources[variant].append("commandline")
        dfs.append(variants_to_dataframe(variants))

    df = dfs.pop(0)
    for other_df in dfs:
        df = pandas.merge(
            df,
            other_df,
            how='outer',
            on=["variant"] + STANDARD_DATAFRAME_COLUMNS)

    genomes = df["genome"].unique()
    if len(genomes) > 1:
        raise ValueError(
                "Mixing references is not supported. "
                "Reference genomes: %s" % (", ".join(genomes)))

    df["sources"] = [" ".join(variant_to_sources[v]) for v in df.variant]
    return df

def load_as_dataframe(
        filename,
        loader=None,
        filters=None,
        name=None,
        genome=None,
        max_variants=None,
        only_passing=True,
        metadata_column_prefix=''):

    if name is None:
        name = filename

    if loader is None:
        if (filename.endswith(".vcf") or filename.endswith(".vcf.gz")):
            # Load from VCF
            def loader(filename):
                collection = varcode.load_vcf_fast(
                    filename,
                    genome=genome,
                    max_variants=max_variants,
                    only_passing=only_passing,
                    allow_extended_nucleotides=True)
                return variants_to_dataframe(
                    collection,
                    collection.metadata,
                    metadata_column_prefix=metadata_column_prefix)

        elif (filename.endswith(".csv") or filename.endswith(".csv.gz")):
            # Load from csv
            def loader(filename):
                # Ignores only_passing
                df = pandas.read_csv(filename, nrows=max_variants)
                for column in ['ref', 'alt']:
                    df[column] = df[column].fillna('')
                df["variant"] = [
                    dataframe_row_to_variant(row) for (i, row) in df.iterrows()
                ]
                return df
        else:
            raise ValueError(
                "Unsupported input file extension for variants: %s" % filename)

    df = loader(filename)

    if 'genome' not in df:
        df["genome"] = genome

    df["variant"] = [
        dataframe_row_to_variant(row) for (i, row) in df.iterrows()
    ]

    if filters:
        df = df[[
            bool(all(
                evaluate_variant_expression(
                    expression, row.to_dict(), row.variant)
                for expression in filters))
            for (i, row) in df.iterrows()
        ]]

    return df

def evaluate_variant_expression(
        expression,
        metadata,
        variant,
        error_value=evaluation.RAISE,
        extra_bindings={}):

    if typechecks.is_string(expression):
        extra_bindings = {
            'inclusive_start': variant.start,
            'inclusive_end': variant.end,
            'interbase_start': variant.start - 1,
            'interbase_end': variant.end,
            'variant': variant,
            'metadata': metadata,
        }
        extra_bindings.update(metadata)
        bindings = evaluation.EvaluationEnvironment([variant], extra_bindings)
        return evaluation.evaluate_expression(
            expression,
            bindings,
            error_value=error_value)
    else:
        return expression(variant)  

def variants_to_dataframe(
        variants, metadata=None, metadata_column_prefix=""):
    def record(variant):
        d = {
            'variant': variant,
            'genome': str(variant.reference_name),
            'contig': variant.contig,
            'interbase_start': variant.start - 1,
            'interbase_end': variant.end,
            'ref': variant.ref,
            'alt': variant.alt,
        }
        if metadata:
            for (name, value) in metadata.get(variant, {}).items():
                if name == 'info':
                    for (info_col, value) in value.items():
                        column = '%sinfo:%s' % (
                            metadata_column_prefix, info_col)
                        d[column] = value
                else:
                    d["%s%s" % (metadata_column_prefix, name.lower())] = value
        return d

    df = pandas.DataFrame.from_records([record(v) for v in variants])
    column_indices = dict(
        (column, i) for (i, column) in enumerate(STANDARD_DATAFRAME_COLUMNS))
    columns = sorted(df.columns, key=lambda col: column_indices.get(col, 100))
    return df[columns]

def dataframe_row_to_variant(row):
    return varcode.Variant(
            ensembl=row.genome,
            contig=row.contig,
            start=row.interbase_start + 1,
            ref=row.ref,
            alt=row.alt,
            allow_extended_nucleotides=True)

def dataframe_to_variants(df):
    for column in STANDARD_DATAFRAME_COLUMNS:
        if column not in df:
            raise ValueError("Missing column: %s" % column)

    extra_columns = [
        c for c in df.columns if c not in STANDARD_DATAFRAME_COLUMNS
    ]
    metadata = collections.OrderedDict()
    for (i, row) in df.iterrows():
        variant = dataframe_row_to_variant(row)
        # We ignore the interbase_end field.
        metadata[variant] = dict((c, row[c]) for c in extra_columns)

    return varcode.VariantCollection(metadata.keys(), metadata=metadata)

def load_csv(filename, genome=None):
    # Genome is ignored for now.
    df = pandas.read_csv(filename)
    return dataframe_to_variants(df)
