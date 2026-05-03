# dcinside-apk
This repository use GitHub Actions to automatically patch APKs.

It use Release Attestations to provide trusted APKs.

It use [Ample ReVanced patches](https://github.com/AmpleReVanced/revanced-patches)

## Automation

`CI` polls `AmpleReVanced/revanced-patches` releases hourly, including prereleases. If the upstream tag has not been released here yet, `Build` creates both APKs:

- `dcinside-{version}-revanced-{patches_commit}-unclone.apk`
- `dcinside-{version}-revanced-{patches_commit}-clone.apk`

The stock app is resolved from APKPure's `app_version` API for `com.dcinside.app.android` with `arm64-v8a` filtering. The build extracts the latest signed APK/XAPK URL and version metadata from the binary API response. XAPK inputs are merged with APKEditor before patching.

## Credits
- [morphe](https://github.com/MorpheApp) - patcher
- [revanced](https://github.com/ReVanced) - previous patcher
- [@REAndroid's APKEditor](https://github.com/REAndroid/APKEditor) - Used in merging split apks
- [piko](https://github.com/crimera/twitter-apk) - Some components of this project were taken from piko's twitter-apk repository.
