class HomelabOs < Formula
  include Language::Python::Virtualenv

  desc "Turnkey personal cloud, SMB3 file server, Pi-hole DNS, and media engine CLI"
  homepage "https://github.com/beingbrijesh/homelab-framework"
  url "https://files.pythonhosted.org/packages/source/h/homelab-os/homelab_os-2.0.0.tar.gz"
  sha256 "REPLACE_WITH_PYPI_SDIST_SHA256_ON_RELEASE"
  license "MIT"

  depends_on "curl"
  depends_on "docker"
  depends_on "docker-compose"
  depends_on "git"
  depends_on "openssl@3"
  depends_on "python@3.12"
  depends_on "tailscale"

  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      Before running `homelab init --start`, ensure the Docker daemon is running:
        macOS: open -a Docker (or OrbStack / Colima)
        Linux: sudo systemctl enable --now docker

      Initialize your Homelab OS workspace:
        homelab doctor
        homelab init -y --start
    EOS
  end

  test do
    assert_match "homelab-os", shell_output("#{bin}/homelab --version")
    assert_match "Homelab OS", shell_output("#{bin}/homelab --help")
  end
end
