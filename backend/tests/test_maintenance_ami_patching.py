"""Regression coverage for the AMI lines the maintenance modals rewrite.

Run from backend/: python -m unittest discover -s tests -v

Two defects reached main through these patchers and had to be cleaned up by
hand in df738c00 (cmscloud-devops):

1. A GovCloud AMI id was labelled ``us-east-1``, because the EKS upgrade path
   reused JFrog's patcher and JFrog hardcodes its own region. The id is only
   valid in us-gov-west-1, so the comment pointed at an image that does not
   exist in the region it named.
2. Six files reached main with conflict markers still in them. A regex patcher
   will happily rewrite an id inside a conflict block and commit it back, which
   preserves the damage while making it look intentional.

The fixtures below are the real lines from that incident.
"""
import unittest

from app.services.cloudbees_maintenance import CB_ENVS, patch_eks_ami_in_tfvars
from app.services.eks_upgrade import EKS_CLUSTERS
from app.services.jfrog_maintenance import (
    JFROG_AMI_REGION,
    ami_comment,
    conflict_markers,
    patch_ami_in_nodeclass,
    patch_ami_in_tfvars,
)

# us-gov-west-1 image, from the gc-prod-west upgrade to 1.36.
GOV_AMI = "ami-0467be823500a2ff6"
GOV_AMI_NAME = "al2023-eks-1.36-gi-2026-10-14T11-55-15Z"
# us-east-1 image for the same Kubernetes minor: a different id entirely.
EAST_AMI = "ami-08ce853648edd4533"
EAST_AMI_NAME = "al2023-eks-1.36-gi-2026-10-14T11-20-30Z"

GOV_TFVARS = (
    'eks_version                  = "1.35"\n'
    'eks_ami                      = "ami-0891cb222dca676f3"'
    '  # us-gov-west-1 al2023-eks-1.35-gi-2026-09-09T11-48-08Z\n'
)

CONFLICTED_NODECLASS = (
    "  amiSelectorTerms:\n"
    "<<<<<<< HEAD\n"
    '    - id: "ami-0891cb222dca676f3"  # us-gov-west-1 al2023-eks-1.35-gi-2026-09-09T11-48-08Z\n'
    "=======\n"
    f'    - id: "{GOV_AMI}"  # us-east-1 : {GOV_AMI_NAME}\n'
    ">>>>>>> 713aa74d213952253e85ff906c326547cbeff4dd\n"
)


class AmiCommentRegionTests(unittest.TestCase):
    def test_govcloud_id_is_labelled_with_its_own_region(self):
        out = patch_ami_in_tfvars(GOV_TFVARS, GOV_AMI, GOV_AMI_NAME, "us-gov-west-1")
        self.assertIn(f'"{GOV_AMI}"  # us-gov-west-1 : {GOV_AMI_NAME}', out)
        self.assertNotIn("us-east-1", out)

    def test_jfrog_still_labels_its_own_region_without_being_told(self):
        out = patch_ami_in_tfvars(GOV_TFVARS, EAST_AMI, EAST_AMI_NAME)
        self.assertIn(f"# {JFROG_AMI_REGION} : {EAST_AMI_NAME}", out)

    def test_every_govcloud_cluster_has_a_region_to_pass(self):
        # The patch call reads cfg["region"], so a cluster missing it would
        # silently fall back to JFrog's us-east-1 again.
        for key, cfg in EKS_CLUSTERS.items():
            self.assertTrue(cfg.get("region"), f"{key} has no region")
        for key, cfg in CB_ENVS.items():
            self.assertTrue(cfg.get("controller_ami_region"), f"{key} has no controller region")
            self.assertTrue(cfg.get("agent_ami_region"), f"{key} has no agent region")

    def test_cbj_and_eks_paths_write_the_same_comment(self):
        # They had drifted to "region name" and "region : name", which made it
        # impossible to tell from a file which path had touched a line.
        self.assertEqual(
            patch_eks_ami_in_tfvars(GOV_TFVARS, GOV_AMI, GOV_AMI_NAME, "us-gov-west-1"),
            patch_ami_in_tfvars(GOV_TFVARS, GOV_AMI, GOV_AMI_NAME, "us-gov-west-1"),
        )

    def test_no_comment_when_the_name_is_unknown(self):
        self.assertEqual(ami_comment("", "us-gov-west-1"), "")


class StaleCommentTests(unittest.TestCase):
    def test_a_comment_naming_the_old_image_is_dropped_not_kept(self):
        # jfrog/prod ended up with the October 1.35 id under a 1.34 label.
        line = '    - id: "ami-0aaa1111bbbb2222c"  # us-east-1 : al2023-eks-1.34-gi-2026-08-15T00-00-00Z\n'
        out = patch_ami_in_nodeclass(line, "ami-034fea2516370e320")
        self.assertIn('"ami-034fea2516370e320"', out)
        self.assertNotIn("1.34", out)

    def test_an_unrelated_comment_survives(self):
        line = '    - id: "ami-0aaa1111bbbb2222c"  # pinned by CLDSPT-112756, do not bump\n'
        out = patch_ami_in_nodeclass(line, "ami-034fea2516370e320")
        self.assertIn("pinned by CLDSPT-112756", out)

    def test_alias_selectors_are_left_alone(self):
        # arm64 pools track al2023@latest and must not be pinned to an x86 image.
        content = "    - alias: al2023@latest\n"
        self.assertEqual(patch_ami_in_nodeclass(content, GOV_AMI, GOV_AMI_NAME), content)


class ConflictMarkerTests(unittest.TestCase):
    def test_the_real_conflicted_file_is_detected(self):
        self.assertTrue(conflict_markers(CONFLICTED_NODECLASS))

    def test_clean_content_is_not_flagged(self):
        self.assertFalse(conflict_markers(GOV_TFVARS))

    def test_a_divider_in_a_comment_is_not_a_conflict(self):
        self.assertFalse(conflict_markers("# ======= node pools =======\nkey: value\n"))

    def test_every_marker_kind_counts(self):
        for marker in ("<<<<<<< HEAD", "=======", ">>>>>>> abc123"):
            self.assertTrue(conflict_markers(f"a: 1\n{marker}\nb: 2\n"), marker)


if __name__ == "__main__":
    unittest.main()
