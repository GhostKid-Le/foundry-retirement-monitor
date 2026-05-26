$k = "C:\Users\lewang2\.azure-kubectl\kubectl.exe"
& $k -n foundry-monitor get jobs
& $k -n foundry-monitor logs -l job-name=manual-20260526185255 --tail=60
