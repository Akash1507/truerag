output "atlas_peering_connection_id" {
  value = var.enable_atlas_peering ? mongodbatlas_network_peering.this[0].connection_id : null
}
