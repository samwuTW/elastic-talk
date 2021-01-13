# Elastictalk
Elastictalk is a AWS ebcli extend library

## Usage
```shell-script
# Show commands
et

# Show global argument setting
et --help

# Show commands' argument setting
# et <command> --help
# Ex:
et save_env_var --help

# Use command with arguments
elastictalk.py take_rds_snapshot rds_id --rds_snapshot_id=new_rds_snapshot_id
```
