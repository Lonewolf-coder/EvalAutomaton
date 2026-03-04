/**
 * GovernIQ Dashboard — Interactive features
 */

document.addEventListener('DOMContentLoaded', () => {
    // Auto-expand evidence cards on click
    document.querySelectorAll('.evidence-card__header').forEach(header => {
        header.style.cursor = 'pointer';
        header.addEventListener('click', () => {
            const content = header.nextElementSibling;
            if (content) {
                content.style.display = content.style.display === 'none' ? 'block' : 'none';
            }
        });
    });

    // Score animation
    document.querySelectorAll('.score-value, .score-value-large').forEach(el => {
        const target = parseFloat(el.textContent);
        let current = 0;
        const step = target / 30;
        const timer = setInterval(() => {
            current += step;
            if (current >= target) {
                current = target;
                clearInterval(timer);
            }
            el.textContent = current.toFixed(1) + '%';
        }, 20);
    });
});
