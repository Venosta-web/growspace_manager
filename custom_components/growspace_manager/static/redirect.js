customElements.define('growspace-manager-redirect', class extends HTMLElement {
    connectedCallback() {
        history.pushState(null, '', '/config/integrations/integration/growspace_manager');
        window.dispatchEvent(new CustomEvent('location-changed'));
    }
});
