terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    mongodbatlas = {
      source  = "mongodb/mongodbatlas"
      version = "~> 1.24"
    }
  }
}

resource "mongodbatlas_network_peering" "this" {
  count = var.enable_atlas_peering ? 1 : 0

  project_id             = var.atlas_project_id
  container_id           = var.atlas_container_id
  accepter_region_name   = var.aws_region
  provider_name          = "AWS"
  route_table_cidr_block = var.vpc_cidr
  vpc_id                 = var.vpc_id
  aws_account_id         = var.aws_account_id
}

resource "aws_vpc_peering_connection_accepter" "this" {
  count = var.enable_atlas_peering ? 1 : 0

  vpc_peering_connection_id = mongodbatlas_network_peering.this[0].connection_id
  auto_accept               = true
}

resource "aws_route" "atlas_private_routes" {
  count = var.enable_atlas_peering ? length(var.private_route_table_ids) : 0

  route_table_id            = var.private_route_table_ids[count.index]
  destination_cidr_block    = var.atlas_cidr_block
  vpc_peering_connection_id = mongodbatlas_network_peering.this[0].connection_id
}
