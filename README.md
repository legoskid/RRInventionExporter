# RRInventionExporter

This is vibecoded btw

It downloads your inventions that you give the script, and their misc data (like holotars/samplers) and saves them to a local folder.

Get your Authorization token from RecNet first. You can easily do that by opening inspect element on the RecNet website, going to the network tab, and looking for requests like `/account/me`. The Authorization token will be in the headers of that request.

Next, get a JSON array of inventions you want to export. Just send a request to `http://api.rec.net/api/inventions/v2/mine`(?) with your authorization token, and you should get a JSON array of your inventions. You can filter that array to only include the inventions you want to export, and then save that array to a file.

Then just run the script with the arguments --token (no bearer) and --json and everything will be downloaded.

## Downloading deleted or offsale inventions
This should work. The inventions API should return these.

>[!WARNING]
> I don't know how to decode the protobuf to get the exact string when downloading misc data, so I just check for .htr, .jpg, .png. So check for errors downloading files in the console!