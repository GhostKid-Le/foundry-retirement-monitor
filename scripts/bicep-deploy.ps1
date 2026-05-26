$az = "C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
& $az deployment group create -g rg-foundry-monitor -f infra\main.bicep -o table
