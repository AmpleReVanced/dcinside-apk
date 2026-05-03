# dcinside-apk
This repository use GitHub Actions to automatically patch APKs.

It use Release Attestations to provide trusted APKs.

## Automation

`CI` polls `AmpleReVanced/revanced-patches` releases hourly, including prereleases. If the upstream tag has not been released here yet, `Build` creates both APKs:

- `dcinside-{version}-revanced-{patches_commit}-unclone.apk`
- `dcinside-{version}-revanced-{patches_commit}-clone.apk`

The stock app is always resolved from APKPure's latest DCInside download page through `cloudscraper`. The build extracts the latest `versionCode`, downloads the `arm64-v8a` XAPK from `d.apkpure.com`, merges it with APKEditor, then patches the merged APK.

## Credits
- [morphe](https://github.com/MorpheApp) - patcher
- [revanced](https://github.com/ReVanced) - previous patcher
- [cloudscraper](https://github.com/venomous/cloudscraper) - APKPure Cloudflare challenge handling
- [@REAndroid's APKEditor](https://github.com/REAndroid/APKEditor) - Used in merging split apks
- [piko](https://github.com/crimera/twitter-apk) - Some components of this project were taken from piko's twitter-apk repository.
