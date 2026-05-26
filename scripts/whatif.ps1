$az = "C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
& $az deployment group what-if -g rg-foundry-monitor -f infra\main.bicep --result-format ResourceIdOnly
