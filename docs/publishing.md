# Before publishing

- Review all staged files with `git diff --cached` and `git ls-files`.
- Run `python3 -m unittest discover -s tests -v`.
- Check the full history that will be pushed, not only the working tree. This
  project was reset to fresh history to remove private recovery material and
  obsolete experiments. Do not merge or push an old backup history.
- Never add SSH keys, passwords, Wi-Fi configuration, local machine paths,
  captures of private activity or deployment backups. Ignoring a file does not
  erase a previously committed copy.
- Rotate any credentials previously stored in old copies of this project; a
  local Git reset cannot revoke credentials or remove copies held elsewhere.
- Review the author name/email on the new commit and use a GitHub-provided
  no-reply email if desired. Git identity is not an authentication credential.
- Select a license you own the rights to grant. No license has been chosen on
  your behalf. Confirm rights to the included sensor photograph before release.
- Create the GitHub repository only when ready, add its remote locally and push
  only the new `main` branch. No remote is preconfigured in this project.

The program needs no cloud account or network secrets. Use SSH keys and normal
host-key verification for your own remote administration. The reference meter
is not a runtime dependency. Software tests do not certify SPL accuracy.
