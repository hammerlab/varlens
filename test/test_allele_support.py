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

from __future__ import absolute_import

import functools

from nose.tools import eq_, assert_raises

from varlens.commands import allele_support

from . import data_path, run_and_parse_csv, cols_concat

run = functools.partial(run_and_parse_csv, allele_support.run)

expected_cols = [
    "contig", "interbase_start", "interbase_end", "allele", "count",
]

def test_basic():
    result = run([
        "--reads", data_path("CELSR1/bams/bam_5.bam"),
        "--locus", "chr22:46929963",
        "--locus", "chr22:46929964",
    ])
    eq_(cols_concat(result, expected_cols),
        {"22-46929962-46929963-C-60", "22-46929963-46929964-A-81"})

    result = run([
        "--reads", data_path("CELSR1/bams/bam_5.bam"),
        "--locus", "chr22:46929963",
        "--locus", "chr22:46929964",
        "--read-filter", "is_reverse"
    ])
    eq_(cols_concat(result, expected_cols),
        {"22-46929962-46929963-C-37", "22-46929963-46929964-A-47"})

    result = run([
        "--reads", data_path("CELSR1/bams/bam_5.bam"),
        "--locus", "chr22:46929963",
        "--locus", "chr22:46929964",
        "foo:is_reverse",
    ])
    eq_(cols_concat(result, expected_cols + ["foo"]),
        {"22-46929962-46929963-C-60-37", "22-46929963-46929964-A-81-47"})

    result = run([
        "--reads", data_path("gatk_mini_bundle_extract.bam"),
        "--locus", "chr20:10008951",
        "is_reverse",
    ])
    eq_(cols_concat(result, expected_cols + ["is_reverse"]),
        {"20-10008950-10008951-C-4-1", "20-10008950-10008951-A-1-0"})
    

def test_simple():
    result = run([
        "--reads", data_path("CELSR1/bams/bam_0.bam"),
        "--variants", data_path("CELSR1/vcfs/vcf_1.vcf#genome=b37"),
    ])
    eq_(cols_concat(result, ["contig", "interbase_start", "interbase_end"]),
        {"22-46931059-46931060", "22-46931061-46931062"})

    pick_first_variant = [
        "ref=='A'",
        "alt=='C'",
        "inclusive_start==46931060",
        "interbase_start==46931059",
        "interbase_end==46931060",
    ]
    for variant_filter in pick_first_variant:
        result = run([
            "--reads", data_path("CELSR1/bams/bam_0.bam"),
            "--variants", data_path("CELSR1/vcfs/vcf_1.vcf#genome=b37"),
            "--variant-filter", variant_filter,
        ])
        yield (
            eq_,
            cols_concat(
                result, ["contig", "interbase_start", "interbase_end"]),
            {"22-46931059-46931060"})
