sudo cp 91-dymo-labelmanager-pnp.rules /etc/udev/rules.d/
sudo cp dymo-labelmanager-pnp.conf /etc/usb_modeswitch.d/
sudo systemctl restart udev.service