Source artwork for the mouse picture shown in the app.

ghost_x_pro_amkette.png   official EvoFox Ghost X Pro product image, downloaded from the Amkette product page
                          https://www.amkette.com/products/evofox-ghost-x-pro-tri-mode-wireless-gaming-mouse
                          (image: cdn/shop/files/GhostX.1617.png, 1920 px).  (c) Amkette / EvoFox.
zones_px.json             clickable button areas, in pixels of the source image

Rebuild the app's artwork (needs Pillow, development only):
    python tools/make_mouse_assets.py assets_src/ghost_x_pro_amkette.png --zones-px assets_src/zones_px.json
